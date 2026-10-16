"""Heartbeat routes consume scheduler behavior and preserve bounded authority."""

import json
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agno.agent import Agent
from agno.company import Product
from agno.company.manager import CompanyManager
from agno.company.routines import _RoutineAuthorization, load_routine_skills
from agno.db.schemas.scheduler import Schedule
from agno.db.sqlite import SqliteDb
from agno.os import AgentOS, CompanyConfig
from agno.os.authz.run_context import restore_authorization
from agno.run.authorization import AUTHORIZATION_HEADER, authorization_scope
from agno.scheduler.executor import ScheduleExecutor


@pytest.fixture
def system(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "company.db"))
    agent = Agent(id="reader", telemetry=False)
    os = AgentOS(db=db, agents=[agent], company=CompanyConfig(), telemetry=False)
    with TestClient(os.get_app()) as client:
        yield client, os, db
    db.close()


def test_routine_scheduler_wrappers(system):
    client, os, db = system
    product = client.post("/company/products", json={"name": "Docs"}).json()
    body = dict(
        product_id=product["id"],
        name="intake",
        template="intake",
        executor_type="agent",
        executor_id="reader",
        cron_expr="0 * * * *",
    )
    response = client.post("/company/routines", json=body)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["managed_by"] == "company"
    assert row["target_id"] == "reader"
    assert row["payload"]["metadata"] == {"product_id": product["id"], "template": "intake", "auto_accept": False}
    assert row["payload"]["message"] == load_routine_skills().get_skill("intake").instructions
    assert db.get_product(product["id"])["metadata"]["routine_ids"] == [row["id"]]
    path = "/company/routines/" + row["id"]
    assert client.post(path + "/pause").json()["enabled"] is False
    assert client.post(path + "/resume").json()["enabled"] is True
    assert client.patch(path, json={"instructions": "Check quietly"}).status_code == 200
    assert db.get_schedule(row["id"])["payload"]["message"] == "Check quietly"
    assert client.patch(path, json={"auto_accept": True}).status_code == 422
    assert client.get(path + "/runs").json()["meta"]["total_count"] == 0
    assert len(client.get("/company/routines").json()["data"]) == 1


@pytest.mark.parametrize("field,value", [("cron_expr", "bad cron"), ("timezone", "not/a/timezone")])
def test_invalid_setup_does_not_create_records(system, field, value):
    client, _, db = system
    routine = dict(name="intake", template="intake", executor_type="agent", executor_id="reader", cron_expr="0 * * * *")
    routine[field] = value
    response = client.post("/company/setup", json={"name": "Invalid", "routines": [routine]})
    assert response.status_code == 422
    assert db.get_products()[1] == 0


@pytest.mark.asyncio
async def test_summary_uses_telegram_interface_transport(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from agno.company.summary import adeliver_summary

    bot = SimpleNamespace(send_message=AsyncMock(), close_session=AsyncMock())
    factory = Mock(return_value=bot)
    monkeypatch.setattr("telebot.async_telebot.AsyncTeleBot", factory)
    interface = SimpleNamespace(type="telegram", token="configured-token")
    await adeliver_summary([interface], "telegram", "123", "Product report")
    factory.assert_called_once_with("configured-token")
    assert bot.send_message.await_args.args[:2] == (123, "Product report")
    bot.close_session.assert_awaited_once()


def test_sources_setup_restart_and_diagnostics(system, tmp_path, monkeypatch):
    client, os, db = system
    path = tmp_path / "readme.md"
    path.write_text("# Release\nNew capability.\n")
    body = {
        "name": "AgentOS",
        "sources": [{"type": "markdown", "reference": str(path), "credential_ref": "HEARTBEAT_TOKEN"}],
    }
    first = client.post("/company/setup", json=body)
    assert first.status_code == 201, first.text
    assert client.patch("/company/products/" + first.json()["id"], json={"name": "Human edit"}).status_code == 200
    client.post("/company/products", json={"name": "Later Product"}).raise_for_status()
    second = client.post("/company/setup", json=body)
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["name"] == "Human edit"
    sources = client.get("/company/sources").json()["data"]
    assert len(sources) == 1
    manager = CompanyManager(db)
    monkeypatch.setenv("HEARTBEAT_TOKEN", "never-forward-this-value")
    evidence = manager.read_source(sources[0]["id"], "run-1")
    assert "never-forward-this-value" not in json.dumps(evidence)
    from agno.os.diagnostics import run_diagnostics

    assert next(c for c in run_diagnostics(os).checks if c.name == "env:HEARTBEAT_TOKEN").status == "PASS"
    monkeypatch.delenv("HEARTBEAT_TOKEN")
    assert next(c for c in run_diagnostics(os).checks if c.name == "env:HEARTBEAT_TOKEN").status == "FAIL"
    assert client.delete("/company/sources/" + sources[0]["id"]).status_code == 204
    assert client.get("/company/sources").json()["data"] == []
    assert client.post("/company/sources/" + sources[0]["id"] + "/restore").status_code == 200


@pytest.mark.asyncio
async def test_company_metadata_survives_executor_scrub(monkeypatch):
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="test")
    captured = {}

    async def capture(client, url, headers, payload, resource_type, resource_id, timeout_seconds):
        captured.update(payload=payload, headers=headers)
        return {"status": "success"}

    monkeypatch.setattr(executor, "_get_client", AsyncMock())
    monkeypatch.setattr(executor, "_background_run", capture)
    metadata = {"product_id": "p", "template": "intake", "auto_accept": False, "agno_component_version": 99}
    schedule = Schedule(
        id="s",
        name="test",
        cron_expr="0 * * * *",
        endpoint="/agents/reader/runs",
        managed_by="company",
        payload={"message": "Check", "metadata": metadata},
    )
    await executor._call_endpoint(schedule)
    assert json.loads(captured["payload"]["metadata"]) == {
        k: v for k, v in metadata.items() if k != "agno_component_version"
    }
    authority = restore_authorization(None, json.loads(captured["headers"][AUTHORIZATION_HEADER]))
    assert isinstance(authority, _RoutineAuthorization)
    with pytest.raises(PermissionError, match="schedules"):
        authority.require("schedules", "write")
    with pytest.raises(PermissionError, match="schedules"):
        await authority.arequire("schedules", "write")


def test_routine_cannot_accept(system):
    _, _, db = system
    manager = CompanyManager(db)
    product = manager.create("Docs")
    task = manager.create_task(product["id"], "Draft")
    with authorization_scope(lambda: _RoutineAuthorization(None)):
        with pytest.raises(PermissionError, match="cannot accept"):
            manager.transition_task(task["id"], "ready", "self approval", executor_type="agent", executor_id="reader")
    assert manager.get_task(task["id"])["status"] == "backlog"


def test_yaml_and_code_rehydrate_without_reset(tmp_path):
    db = SqliteDb(db_file=str(tmp_path / "declare.db"))
    declaration = Product(name="SDK", purpose="Maintain SDK")
    os = AgentOS(db=db, company=CompanyConfig(products=[declaration]), telemetry=False)
    with TestClient(os.get_app()) as client:
        first = client.get("/company/products").json()["data"][0]
        client.patch("/company/products/" + first["id"], json={"purpose": "Human direction"})
    with TestClient(AgentOS(db=db, company=CompanyConfig(products=[declaration]), telemetry=False).get_app()) as client:
        rows = client.get("/company/products").json()["data"]
        assert len(rows) == 1
        assert rows[0]["purpose"] == "Human direction"
    config = tmp_path / "config.yaml"
    config.write_text("company:\n  products:\n    - name: SDK\n      purpose: stale declaration\n")
    with TestClient(AgentOS(db=db, config=str(config), telemetry=False).get_app()) as client:
        assert client.get("/company/products").json()["data"][0]["purpose"] == "Human direction"
    db.close()


@pytest.mark.parametrize("isolation", [False, True])
def test_sources_and_routines_scopes_and_ownership(tmp_path, isolation):
    from datetime import datetime, timedelta, timezone

    import jwt

    from agno.os.config import AuthorizationConfig

    secret = "heartbeat-isolation-secret"
    scopes = [
        "products:read",
        "products:write",
        "sources:read",
        "sources:write",
        "sources:delete",
        "routines:read",
        "routines:write",
        "schedules:read",
        "schedules:write",
        "agents:reader:run",
    ]

    def headers(user, granted=None):
        return {
            "Authorization": "Bearer "
            + jwt.encode(
                {
                    "sub": user,
                    "aud": "heartbeat",
                    "scopes": scopes if granted is None else granted,
                    "exp": datetime.now(timezone.utc) + timedelta(hours=1),
                },
                secret,
                algorithm="HS256",
            )
        }

    db = SqliteDb(db_file=str(tmp_path / "isolated.db"))
    os = AgentOS(
        id="heartbeat",
        db=db,
        agents=[Agent(id="reader", telemetry=False)],
        company=CompanyConfig(),
        telemetry=False,
        authorization=True,
        authorization_config=AuthorizationConfig(
            verification_keys=[secret], algorithm="HS256", user_isolation=isolation
        ),
    )
    with TestClient(os.get_app()) as client:
        product = client.post("/company/products", headers=headers("alice"), json={"name": "Docs"}).json()
        body = {"product_id": product["id"], "type": "markdown", "reference": "/docs"}
        assert client.post("/company/sources", headers=headers("bob"), json=body).status_code == (
            403 if isolation else 201
        )
        assert client.post("/company/sources", headers=headers("alice"), json=body).status_code == 201
        assert client.get("/company/sources", headers=headers("bob", ["sources:read"])).json()["data"]
        routine = {
            "product_id": product["id"],
            "name": "intake",
            "template": "intake",
            "executor_type": "agent",
            "executor_id": "reader",
            "cron_expr": "0 * * * *",
        }
        assert (
            client.post(
                "/company/routines",
                headers=headers("alice", [s for s in scopes if s != "schedules:write"]),
                json=routine,
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/company/routines",
                headers=headers("alice", [s for s in scopes if s != "agents:reader:run"]),
                json=routine,
            ).status_code
            == 403
        )
        assert client.post("/company/routines", headers=headers("alice"), json=routine).status_code == 201
    db.close()
