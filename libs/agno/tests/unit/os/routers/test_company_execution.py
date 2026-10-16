"""Execution gates, shared reads and existing run ownership rules."""

import asyncio
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import CompanyManager
from agno.company.execution import _ExecutorAuthorization
from agno.db.sqlite import SqliteDb
from agno.job_queue import QueueConfig
from agno.job_queue.store import InMemoryQueueStore
from agno.os import AgentOS, CompanyConfig
from agno.os.authz import Authorization
from agno.os.job_queue import QueueWorker
from agno.registry import Registry
from agno.tools.scheduler import SchedulerTools

SECRET = "company-execution-tests-secret-at-least-32-bytes"
SCOPES = ["products:read", "products:write", "tasks:read", "tasks:write", "wiki:read", "agents:writer:run"]


def headers(user="alice", scopes=None):
    return {
        "Authorization": "Bearer "
        + jwt.encode(
            {
                "sub": user,
                "aud": "company-execution",
                "scopes": SCOPES if scopes is None else scopes,
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            SECRET,
            algorithm="HS256",
        )
    }


@pytest.fixture(params=[False, True], ids=["shared", "isolated"])
def system(request, tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    writer = Agent(id="writer", db=db)
    os = AgentOS(
        id="company-execution",
        db=db,
        registry=Registry(agents=[writer]),
        company=CompanyConfig(),
        telemetry=False,
        user_isolation=request.param,
        authorization=Authorization(verification_keys=[SECRET], algorithm="HS256"),
    )
    app = os.get_app()
    config = QueueConfig(durable=True)
    queue = QueueWorker(InMemoryQueueStore(), lambda *a, **k: writer, config, authorization_app=app)
    queue._company_db = db
    app.state.queue_worker = queue
    yield TestClient(app), db, os, queue
    db.close()


def accepted(client):
    product = client.post("/company/products", json={"name": "SDK"}, headers=headers()).json()
    task = client.post(
        "/company/tasks", json={"product_id": product["id"], "title": "Draft", "brief": "Write"}, headers=headers()
    ).json()
    path = f"/company/tasks/{task['id']}"
    response = client.post(
        path + "/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "writer"},
        headers=headers(),
    )
    assert response.status_code == 200, response.text
    return path, response.json()


def test_missing_executor_at_acceptance_and_registry_only_mount(system):
    client, db, os, queue = system
    path, task = accepted(client)
    assert client.post(path + "/runs", headers=headers()).status_code == 202
    other = client.post(
        "/company/tasks", json={"product_id": task["product_id"], "title": "Other"}, headers=headers()
    ).json()
    denied = client.post(
        f"/company/tasks/{other['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": "agent", "executor_id": "missing"},
        headers=headers(scopes=["agent_os:admin"]),
    )
    assert denied.status_code == 409
    assert client.get(f"/company/tasks/{other['id']}", headers=headers()).json()["status"] == "backlog"


def test_start_requires_current_run_and_wiki_permissions(system):
    client, db, os, queue = system
    path, task = accepted(client)
    for omitted in ("agents:writer:run", "wiki:read", "tasks:write"):
        response = client.post(path + "/runs", headers=headers(scopes=[scope for scope in SCOPES if scope != omitted]))
        assert response.status_code == 403, response.text
    assert client.get(path, headers=headers()).json()["status"] == "ready"
    os.registry.agents.clear()
    assert client.post(path + "/runs", headers=headers()).status_code == 409


def test_attention_history_and_duplicates_are_shared(system):
    client, db, os, queue = system
    path, task = accepted(client)
    start = client.post(path + "/runs", headers=headers())
    assert start.status_code == 202, start.text
    duplicate = client.post(path + "/runs", headers=headers("bob"))
    assert duplicate.status_code == 202 and duplicate.json()["run_id"] == start.json()["run_id"]
    assert client.get(path + "/runs", headers=headers("bob")).json()["meta"]["total_count"] == 1
    assert client.get("/company/attention", headers=headers("bob")).status_code == 200
    assert client.get("/company/attention", headers=headers(scopes=[])).status_code == 403
    cancelled = client.post(f"/company/runs/{start.json()['run_id']}/cancel", headers=headers())
    assert cancelled.status_code == 200, cancelled.text


def test_unaccepted_no_queue_and_request_overrides(system):
    client, db, os, queue = system
    path, task = accepted(client)
    assert (
        client.post(path + "/runs", json={"message": "smuggle", "session_id": "foreign"}, headers=headers()).status_code
        == 422
    )
    client.app.state.queue_worker = None
    assert client.post(path + "/runs", headers=headers()).status_code == 503
    assert client.get(path, headers=headers()).json()["status"] == "ready"


def test_python_acceptance_also_validates_registry(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "registry.db"))
    manager = CompanyManager(db)
    product = manager.create("SDK")
    task = manager.create_task(product["id"], "Draft")
    with pytest.raises(ValueError, match="missing"):
        manager.transition_task(task["id"], "ready", "Accept", executor_type="agent", executor_id="writer")
    manager.registry = Registry(agents=[Agent(id="writer", tools=[SchedulerTools(db=db)])])
    with pytest.raises(ValueError, match="SchedulerTools"):
        manager.transition_task(task["id"], "ready", "Accept", executor_type="agent", executor_id="writer")
    db.close()


def test_company_executor_cannot_acquire_schedule_mutation_authority():
    authority = _ExecutorAuthorization(None)
    for action in ("write", "delete"):
        with pytest.raises(PermissionError, match="schedules"):
            authority.require("schedules", action)
        with pytest.raises(PermissionError, match="schedules"):
            asyncio.run(authority.arequire("schedules", action))
    authority.require("schedules", "read")


def test_run_routes_without_company_database():
    app = AgentOS(company=CompanyConfig(), telemetry=False).get_app()
    with TestClient(app) as client:
        assert client.get("/company/runs/missing").status_code == 503
        assert client.post("/company/runs/missing/cancel").status_code == 503


def test_missing_product_context_does_not_reserve_execution(system):
    client, db, os, queue = system
    path, task = accepted(client)
    assert db.delete_product(task["product_id"])
    response = client.post(path + "/runs", headers=headers())
    assert response.status_code == 404, response.text
    assert db.get_task(task["id"])["job_id"] is None


@pytest.mark.asyncio
async def test_automatic_pickup_keeps_accepting_identity_and_run_scope(system):
    from agno.company.routines import _CompanyScheduleExecutor
    from agno.run.authorization import AUTHORIZATION_KEY

    client, db, os, queue = system
    path, task = accepted(client)
    client.app.state.internal_service_token = "company-internal"
    executor = _CompanyScheduleExecutor(
        os, client.app, base_url="http://test", internal_service_token="company-internal"
    )
    stored = db.get_task(task["id"])
    snapshot = stored["transitions"][-1][AUTHORIZATION_KEY]
    assert snapshot["context"]["principal_id"] == "alice"
    assert AUTHORIZATION_KEY not in str(client.get(path, headers=headers()).json())
    result = await executor._dispatch(stored)
    job = await queue.store.get_job(result["run_id"])
    assert job["user_id"] == "alice", job
    assert "schedules:write" not in str(job["payload"].get(AUTHORIZATION_KEY))
    # A different executor cannot reuse the caller's accepted run grant.
    with pytest.raises(PermissionError):
        from agno.os.authz.run_context import restore_authorization

        await restore_authorization(client.app, snapshot).arequire("agents", "run", "another-agent")


def test_auto_accept_human_scope_and_executor_fence(system):
    client, db, os, queue = system
    scopes = SCOPES + ["routines:write", "routines:read", "schedules:write", "schedules:read"]
    product = client.post("/company/products", json={"name": "Docs"}, headers=headers()).json()
    body = {
        "product_id": product["id"],
        "name": "intake",
        "template": "intake",
        "executor_type": "agent",
        "executor_id": "writer",
        "cron_expr": "0 * * * *",
        "auto_accept": {"executor_type": "agent", "executor_id": "writer", "required_checks": ["executor_registered"]},
    }
    for missing in ("schedules:write", "tasks:write", "agents:writer:run"):
        response = client.post(
            "/company/routines", json=body, headers=headers(scopes=[scope for scope in scopes if scope != missing])
        )
        assert response.status_code == 403, response.text
    response = client.post("/company/routines", json=body, headers=headers(scopes=scopes))
    assert response.status_code == 201, response.text
    routine = response.json()
    assert "_agno_company_acceptance" not in str(routine)
    assert db.get_schedule(routine["id"])["payload"]["_agno_company_acceptance"]["user_id"] == "alice"
    body["name"] = "unknown-check"
    body["auto_accept"]["required_checks"] = ["unknown"]
    assert client.post("/company/routines", json=body, headers=headers(scopes=scopes)).status_code == 422
    # The same check applies on the generic schedule surface; the persisted
    # authority is freshly stamped, never a supplied payload's forged snapshot.
    raw = db.get_schedule(routine["id"])["payload"]
    raw["metadata"]["auto_accept"]["executor_id"] = "another-agent"
    assert (
        client.patch(f"/schedules/{routine['id']}", json={"payload": raw}, headers=headers(scopes=scopes)).status_code
        == 403
    )


@pytest.mark.asyncio
async def test_routine_payload_cannot_grant_or_widen_authorization(system, monkeypatch):
    import json
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from fastapi import HTTPException

    from agno.company.routines import _stamp_auto_accept
    from agno.db.schemas.scheduler import Schedule
    from agno.os.authz.run_context import restore_authorization
    from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY, authorization_scope
    from agno.scheduler import ScheduleExecutor

    client, db, os, queue = system
    _, task = accepted(client)
    human = db.get_task(task["id"])["transitions"][-1][AUTHORIZATION_KEY]
    captured = {}

    async def capture(_client, _url, headers, payload, *args):
        captured.update(headers=headers, payload=payload)
        return {"status": "success"}

    executor = ScheduleExecutor(base_url="http://test", internal_service_token="internal")
    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    monkeypatch.setattr(executor, "_background_run", capture)
    await executor._call_endpoint(
        Schedule(
            id="routine",
            name="intake",
            cron_expr="* * * * *",
            endpoint="/agents/writer/runs",
            managed_by="company",
            payload={
                AUTHORIZATION_KEY: human,
                "_agno_company_acceptance": {"user_id": "admin"},
                "metadata": {
                    "auto_accept": {"executor_id": "another-agent"},
                    AUTHORIZATION_KEY: {"context": {"scopes": ["agent_os:admin"]}},
                    "company_routine_unscoped": True,
                },
            },
        )
    )
    assert "_agno_company_acceptance" not in captured["payload"]
    authority = restore_authorization(client.app, json.loads(captured["headers"][AUTHORIZATION_HEADER]))
    await authority.arequire("agents", "run", "writer")
    with pytest.raises(PermissionError):
        await authority.arequire("agents", "run", "another-agent")
    with pytest.raises(PermissionError, match="schedules"):
        await authority.arequire("schedules", "write")
    request = SimpleNamespace(state=SimpleNamespace(is_internal_service=False))
    with authorization_scope(lambda: authority):
        with pytest.raises(HTTPException) as error:
            await _stamp_auto_accept(
                request, {"metadata": {"auto_accept": {"executor_type": "agent", "executor_id": "writer"}}}
            )
        assert error.value.status_code == 403
        with pytest.raises(PermissionError, match="cannot accept"):
            CompanyManager(db, os.registry).transition_task(
                task["id"], "ready", "self-accept", executor_type="agent", executor_id="writer"
            )
