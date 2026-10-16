"""Task execution through real routes, run storage and a PostgreSQL durable queue."""

import asyncio
import json
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from agno.agent import Agent
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.job_queue import QueueConfig
from agno.models.base import Model
from agno.models.message import MessageMetrics
from agno.models.response import ModelResponse
from agno.os import AgentOS, CompanyConfig
from agno.os.job_queue import QueueWorker, resolve_queue_store
from agno.team import Team
from agno.workflow import Step, StepOutput, Workflow


class OfflineModel(Model):
    def __init__(self):
        super().__init__(id="offline", provider="test")

    def invoke(self, *args, **kwargs):
        return ModelResponse(
            role="assistant", content="Completed evidence-based draft", response_usage=MessageMetrics()
        )

    async def ainvoke(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    async def ainvoke_stream(self, *args, **kwargs):
        yield self.invoke(*args, **kwargs)

    def parse_args(self, *args, **kwargs):
        return {}

    def _parse_provider_response(self, response, **kwargs):
        return response

    def _parse_provider_response_delta(self, response):
        return response


def draft(step_input):
    return StepOutput(content="Completed workflow draft")


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def system(request, tmp_path):
    schema = "execution_" + uuid4().hex
    queue_db = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "company.db"))
    agent = Agent(id="writer", model=OfflineModel(), db=db, telemetry=False)
    team = Team(id="editors", model=OfflineModel(), members=[], db=db, telemetry=False)
    workflow = Workflow(id="draft", steps=[Step(name="Draft", executor=draft)], db=db, telemetry=False)
    config = QueueConfig(durable=True, db=queue_db, max_attempts=2, retry_delay_seconds=0)
    os = AgentOS(
        db=db,
        agents=[agent],
        teams=[team],
        workflows=[workflow],
        company=CompanyConfig(),
        queue=config,
        telemetry=False,
    )
    app = os.get_app()
    components = {"writer": agent, "editors": team, "draft": workflow}
    worker = QueueWorker(
        resolve_queue_store(config, db), lambda kind, id, scope=None: components.get(id), config, authorization_app=app
    )
    worker._company_db = db
    app.state.queue_worker = worker
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, db, worker, os, components
    if isinstance(db, AsyncBaseDb):
        await db.close()
    else:
        db.close()
    with queue_db.db_engine.begin() as conn:
        conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
    queue_db.close()


async def accepted(client, kind="agent", id="writer"):
    product = (
        await client.post("/company/products", json={"name": "SDK", "metadata": {"secret": "never-forward"}})
    ).json()
    task = (
        await client.post(
            "/company/tasks",
            json={
                "product_id": product["id"],
                "title": "Draft",
                "brief": "Write a draft",
                "evidence": [{"url": "https://example.com/evidence", "hash": "abc"}],
            },
        )
    ).json()
    response = await client.post(
        f"/company/tasks/{task['id']}/transitions",
        json={"target": "ready", "reason": "Approved", "executor_type": kind, "executor_id": id},
    )
    assert response.status_code == 200, response.text
    return response.json()


async def execute(worker):
    job = await worker.store.claim_job(worker.worker_id, worker.config.lock_grace_seconds)
    assert job is not None
    await worker._execute_claimed(job)
    return await worker.store.get_job(job["id"])


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,id", [("agent", "writer"), ("team", "editors"), ("workflow", "draft")])
async def test_execution_duplicate_context_history_and_attention(system, kind, id):
    client, db, worker, os, _ = system
    value = await accepted(client, kind, id)
    path = f"/company/tasks/{value['id']}"
    starts = await asyncio.gather(client.post(path + "/runs"), client.post(path + "/runs"))
    assert all(r.status_code == 202 for r in starts), [r.text for r in starts]
    assert starts[0].json()["run_id"] == starts[1].json()["run_id"]
    run_id = starts[0].json()["run_id"]
    job = await worker.store.get_job(run_id)
    payload = json.loads(job["payload"]["input"])
    assert set(payload) == {"brief", "wiki", "evidence"}
    assert len(payload["wiki"]) == 4 and payload["evidence"][0]["hash"] == "abc"
    assert "never-forward" not in job["payload"]["input"]
    assert job["idempotency_key"] == f"company:{value['id']}:1" and job["max_attempts"] == 2
    assert (await execute(worker))["status"] == "completed"
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_review" and "draft" in saved["result"]["content"]
    assert saved["session_id"] == value["session_id"]
    duplicate = await client.post(path + "/runs")
    assert duplicate.status_code == 202 and duplicate.json()["run_id"] == run_id
    history = (await client.get(path + "/runs", params={"limit": 1, "page": 1})).json()
    assert history["meta"]["total_count"] == 1
    assert (await client.get("/company/attention", params={"product_id": value["product_id"]})).json() == {
        "proposals": 0,
        "in_review": 1,
        "failed": 0,
    }
    assert (await client.post(path + "/runs", json={"attempt": 2})).status_code == 409
    assert (
        await client.post(path + "/transitions", json={"target": "in_progress", "reason": "Revise"})
    ).status_code == 200
    revision = await client.post(path + "/runs", json={"attempt": 2})
    assert revision.status_code == 202, revision.text
    assert revision.json()["session_id"] == value["session_id"] and revision.json()["run_id"] != run_id
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(path + "/runs", params={"limit": 1, "page": 2})).json()["meta"]["total_count"] == 2


@pytest.mark.asyncio
async def test_cancellation_and_revocation(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    assert response.status_code == 202, response.text
    run_id = response.json()["run_id"]
    assert (await client.post(f"/company/runs/{run_id}/cancel")).status_code == 200
    assert (await worker.store.get_job(run_id))["status"] == "cancelled"
    next_run = await client.post(path + "/runs", json={"attempt": 2})
    assert next_run.status_code == 202, next_run.text
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
    ).status_code == 200
    assert (await execute(worker))["status"] == "failed"
    assert (await client.get(path)).json()["status"] == "backlog"


@pytest.mark.asyncio
async def test_registry_recheck_and_engineering(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    os.registry.agents.clear()
    assert (await client.post(f"/company/tasks/{value['id']}/runs")).status_code == 409
    engineering = await accepted(client, "engineering", "codex")
    response = await client.post(f"/company/tasks/{engineering['id']}/runs")
    assert response.status_code == 409 and "Engineering" in response.text


@pytest.mark.asyncio
async def test_bounded_failure_visible_without_changing_lifecycle(system, monkeypatch):
    client, db, worker, os, components = system
    value = await accepted(client)

    async def fail(*args, **kwargs):
        raise RuntimeError("executor failed")

    monkeypatch.setattr(components["writer"], "arun", fail)
    path = f"/company/tasks/{value['id']}"
    assert (await client.post(path + "/runs")).status_code == 202
    first = await execute(worker)
    assert first["status"] == "queued"
    second = await execute(worker)
    assert second["status"] == "failed" and second["attempt"] == 2
    saved = (await client.get(path)).json()
    assert saved["status"] == "in_progress" and saved["result"]["status"] == "ERROR"
    assert (await client.get("/company/attention")).json()["failed"] == 1
    rows = (await client.get("/company/tasks", params={"failed": "true"})).json()
    assert rows["meta"]["total_count"] == 1 and rows["data"][0]["id"] == value["id"]


@pytest.mark.asyncio
async def test_queue_reconciliation_projects_completion_after_restart(system, monkeypatch):
    client, db, worker, os, components = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    assert (await client.post(path + "/runs")).status_code == 202

    async def lost_settlement(*args, **kwargs):
        return False

    monkeypatch.setattr(worker, "_asettle_ticket", lost_settlement)
    first = await execute(worker)
    assert first["status"] == "running"
    assert (await client.get(path)).json()["status"] == "in_progress"
    # Reclaim by a new worker after a lost lease; it must honor the terminal run row.
    restarted = QueueWorker(
        worker.store, worker.resolve_component, worker.config, authorization_app=worker.authorization_app
    )
    restarted._company_db = db
    queue_db = worker.config.db
    table = queue_db._get_table("jobs")
    with queue_db.Session() as session, session.begin():
        session.execute(table.update().where(table.c.id == first["id"]).values(locked_at=0))
    assert (await execute(restarted))["status"] == "completed"
    assert (await client.get(path)).json()["status"] == "in_review"
    assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_existing_task_table_migrates_idempotently(system):
    from sqlalchemy import Column, MetaData, Table, inspect

    from agno.company.execution import _call
    from agno.db.migrations.manager import MigrationManager
    from agno.db.sqlite.schemas import TASKS_TABLE_SCHEMA

    client, db, worker, os, components = system
    name = "custom_company_tasks"
    new_columns = {"session_id", "job_id", "evidence", "result", "origin", "routine_id", "dedupe_key"}
    schema = getattr(db, "db_schema", None)
    table = Table(name, MetaData(), schema=schema)
    # A real populated table from before execution, using portable JSON for legacy columns.
    for key, definition in TASKS_TABLE_SCHEMA.items():
        if key not in new_columns and not key.startswith("_"):
            table.append_column(
                Column(
                    key,
                    definition["type"],
                    primary_key=definition.get("primary_key", False),
                    nullable=definition.get("nullable", True),
                )
            )

    def create(conn):
        if schema:
            conn.execute(text('CREATE SCHEMA IF NOT EXISTS "' + schema + '"'))
        table.create(conn)
        conn.execute(
            table.insert().values(
                id="existing", title="Keep this", product_id="product", status="backlog", created_at=1, transitions=[]
            )
        )

    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.begin() as conn:
            await conn.run_sync(create)
    else:
        with db.db_engine.begin() as conn:
            create(conn)
    db.tasks_table_name = name
    await _call(db, "upsert_schema_version", name, "3.0.0")
    await MigrationManager(db).up(table_type="tasks")
    await MigrationManager(db).up(table_type="tasks")
    value = await _call(db, "get_task", "existing")
    assert value["title"] == "Keep this" and new_columns <= set(value)
    assert all(value[key] is None for key in new_columns)
    assert await _call(db, "get_latest_schema_version", name) == "3.1.5"

    def inspect_table(conn):
        return inspect(conn).get_indexes(name, schema=schema)

    if isinstance(db, AsyncBaseDb):
        async with db.db_engine.connect() as conn:
            indexes = await conn.run_sync(inspect_table)
    else:
        with db.db_engine.connect() as conn:
            indexes = inspect_table(conn)
    assert {f"idx_{name}_session_id", f"idx_{name}_job_id"} <= {index["name"] for index in indexes}


@pytest.mark.asyncio
async def test_results_cannot_cross_revoked_acceptance(system):
    from agno.company.execution import _call
    from agno.db.schemas.tasks import task_run_id

    client, db, worker, os, _ = system
    value = await accepted(client)
    reserved = await _call(db, "start_task_run", value["id"], 1, (await _call(db, "get_task", value["id"]))["transitions"])
    await _call(db, "transition_task", value["id"], "backlog", "Withdraw")
    await _call(db, "transition_task", value["id"], "ready", "New scope", executor_type="agent", executor_id="writer")
    await _call(db, "transition_task", value["id"], "in_progress", "Manual work")
    assert (
        await _call(
            db,
            "complete_task_run",
            value["id"],
            task_run_id(value["id"], 1),
            {"status": "COMPLETED", "content": "stale"},
            expected_transitions=reserved["transitions"],
        )
        is None
    )
    saved = await _call(db, "get_task", value["id"])
    assert saved["status"] == "in_progress" and saved["result"] is None


@pytest.mark.asyncio
async def test_run_history_and_duplicate_survive_ticket_retention(system):
    client, db, worker, os, _ = system
    value = await accepted(client)
    path = f"/company/tasks/{value['id']}"
    response = await client.post(path + "/runs")
    run_id = response.json()["run_id"]
    assert (await execute(worker))["status"] == "completed"
    table = worker.config.db._get_table("jobs")
    with worker.config.db.Session() as session, session.begin():
        session.execute(table.delete().where(table.c.id == run_id))
    assert (await client.post(path + "/runs")).json()["run_id"] == run_id
    response = await client.get(f"/company/runs/{run_id}")
    assert response.status_code == 200 and response.json()["status"] == "COMPLETED", response.text
    assert (
        await client.post(path + "/transitions", json={"target": "in_progress", "reason": "Revise draft"})
    ).status_code == 200
    revision = await client.post(path + "/runs", json={"attempt": 2})
    assert revision.status_code == 202, revision.text
    assert revision.json()["run_id"] != run_id
    os.registry.agents.clear()
    assert (await client.get(path + "/runs")).json()["meta"]["total_count"] == 2


@pytest.mark.asyncio
async def test_routine_intake_through_scheduler_and_durable_queue(system, tmp_path):
    from agno.company.execution import _call
    from agno.scheduler.executor import ScheduleExecutor
    from agno.tools.company import CompanyTools

    client, db, worker, os, components = system
    path = tmp_path / "release.md"
    path.write_text("A released capability")
    product = (await client.post("/company/products", json={"name": "Docs"})).json()
    source = (
        await client.post(
            "/company/sources", json={"product_id": product["id"], "type": "markdown", "reference": str(path)}
        )
    ).json()

    class IntakeModel(OfflineModel):
        def invoke(self, messages, *args, **kwargs):
            if not any(message.role == "tool" for message in messages):
                return ModelResponse(
                    role="assistant",
                    tool_calls=[
                        {
                            "id": "intake",
                            "type": "function",
                            "function": {
                                "name": "intake_company_source",
                                "arguments": json.dumps({"source_id": source["id"]}),
                            },
                        }
                    ],
                    response_usage=MessageMetrics(),
                )
            return ModelResponse(
                role="assistant",
                content="Source checked; proposals remain in Backlog.",
                response_usage=MessageMetrics(),
            )

    components["writer"].model = IntakeModel()
    components["writer"].tools = [CompanyTools(db)]
    response = await client.post(
        "/company/routines",
        json={
            "product_id": product["id"],
            "name": "intake",
            "template": "intake",
            "executor_type": "agent",
            "executor_id": "writer",
            "cron_expr": "0 * * * *",
        },
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    app = worker.authorization_app
    app.state.internal_service_token = "heartbeat-internal"
    executor = ScheduleExecutor(base_url="http://test", internal_service_token="heartbeat-internal", poll_interval=0)
    original_request = client.request

    async def request_and_work(method, url, **kwargs):
        result = await original_request(method, url, **kwargs)
        if method == "POST" and result.status_code == 202:
            completed = await execute(worker)
            assert completed["status"] == "completed", completed
        return result

    from unittest.mock import AsyncMock

    executor._get_client = AsyncMock(return_value=SimpleClient(request_and_work))
    schedule = await _call(db, "get_schedule", routine["id"])
    first = await executor.execute(schedule, db, release_schedule=False)
    assert first["status"] == "success", first
    rows, total = await _call(db, "get_tasks", product_id=product["id"])
    assert total == 1, first
    assert rows[0]["routine_id"] == routine["id"]
    assert rows[0]["evidence"][0]["run_id"] == first["run_id"]
    assert rows[0]["status"] == "backlog"
    second = await executor.execute(schedule, db, release_schedule=False)
    assert second["status"] == "success", second
    assert (await _call(db, "get_tasks", product_id=product["id"]))[1] == 1
    history = (await client.get("/company/routines/" + routine["id"] + "/runs")).json()
    assert history["meta"]["total_count"] == 2
    assert all(run["status"] == "success" for run in history["data"])


class SimpleClient:
    def __init__(self, request):
        self.request = request


async def automation(system):
    from agno.company.routines import _CompanyScheduleExecutor, _ensure_automation_schedule

    client, db, worker, os, _ = system
    worker._company_schedule_db = db
    executor = _CompanyScheduleExecutor(
        os, worker.authorization_app, base_url="http://test", internal_service_token="test"
    )
    schedule = await _ensure_automation_schedule(db)
    return executor, schedule


async def tick(executor, db):
    from agno.company.execution import _call

    claimed = await _call(db, "claim_due_schedule", str(uuid4()))
    if claimed is None:
        return None
    return await executor.execute(claimed, db)


@pytest.mark.asyncio
async def test_automation_concurrent_ticks_and_restart(system, monkeypatch):
    from agno.company.execution import _call
    from agno.company.routines import _CompanyScheduleExecutor

    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    results = await asyncio.gather(tick(executor, db), tick(executor, db))
    assert sum(result is not None for result in results) == 1
    result = next(result for result in results if result)
    assert result["status"] == "success", result
    saved = await _call(db, "get_task", task["id"])
    assert saved["job_id"] is not None, result
    run_id = saved["job_id"]
    assert (await worker.store.get_job(run_id))["idempotency_key"] == f"company:{task['id']}:1"
    # A new scheduler after submission sees the same durable Task reservation.
    restarted = _CompanyScheduleExecutor(
        os, worker.authorization_app, base_url="http://test", internal_service_token="test"
    )
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    await tick(restarted, db)
    assert (await _call(db, "get_task", task["id"]))["job_id"] == run_id
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(f"/company/tasks/{task['id']}/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_automation_crash_between_reservation_and_queue(system, monkeypatch):
    from agno.company.execution import _call
    from agno.os.routers.company import runs

    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    original = runs._run_route

    async def interrupted(*args, **kwargs):
        raise RuntimeError("process stopped after reservation")

    monkeypatch.setattr(runs, "_run_route", interrupted)
    first = await tick(executor, db)
    reserved = await _call(db, "get_task", task["id"])
    assert reserved["status"] == "in_progress", first
    assert await worker.store.get_job(reserved["job_id"]) is None
    monkeypatch.setattr(runs, "_run_route", original)
    restarted, _ = await automation(system)
    await _call(db, "update_schedule", schedule["id"], next_run_at=0)
    second = await tick(restarted, db)
    assert await worker.store.get_job(reserved["job_id"]) is not None, second
    assert (await execute(worker))["status"] == "completed"
    assert (await client.get(f"/company/tasks/{task['id']}/runs")).json()["meta"]["total_count"] == 1


@pytest.mark.asyncio
async def test_automation_backlog_after_queue_never_executes(system):
    client, db, worker, os, _ = system
    task = await accepted(client)
    executor, schedule = await automation(system)
    result = await tick(executor, db)
    path = f"/company/tasks/{task['id']}"
    assert (await client.get(path)).json()["status"] == "in_progress", result
    assert (
        await client.post(path + "/transitions", json={"target": "backlog", "reason": "Withdraw"})
    ).status_code == 200
    assert (await execute(worker))["status"] == "failed"
    assert (await client.get(path)).json()["status"] == "backlog"
    assert "draft" not in json.dumps((await client.get(path)).json().get("result"))


async def routine_proposal(system, tmp_path, *, policy=None, executor_id="writer"):
    from agno.company.manager import AsyncCompanyManager, CompanyManager
    from agno.company.routines import _manager_call, _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    product = (await client.post("/company/products", json={"name": "Docs"})).json()
    project = (await client.post("/company/projects", json={"product_id": product["id"], "name": "Release"})).json()
    assert (
        await client.post(
            f"/company/projects/{project['id']}/transitions", json={"target": "active", "reason": "Start"}
        )
    ).status_code == 200
    source_path = tmp_path / (product["id"] + ".md")
    source_path.write_text("# Release\nVerified Source material.\n")
    source = (
        await client.post(
            "/company/sources", json={"product_id": product["id"], "type": "markdown", "reference": str(source_path)}
        )
    ).json()
    if policy is None:
        policy = {
            "executor_type": "agent",
            "executor_id": "writer",
            "source_ids": [source["id"]],
            "work_scope": {"product_ids": [product["id"]], "project_ids": [project["id"]]},
            "required_checks": ["project_active", "has_source_evidence", "executor_registered"],
            "limits": {"max_acceptances": 1},
        }
    response = await client.post(
        "/company/routines",
        json={
            "product_id": product["id"],
            "name": "intake",
            "template": "intake",
            "executor_type": "agent",
            "executor_id": "writer",
            "cron_expr": "0 0 * * *",
            "auto_accept": policy,
        },
    )
    assert response.status_code == 201, response.text
    routine = response.json()
    manager = AsyncCompanyManager(db, os.registry) if isinstance(db, AsyncBaseDb) else CompanyManager(db, os.registry)
    evidence = await _manager_call(manager, "read_source", source["id"], "source-run")
    evidence = [{key: value for key, value in item.items() if key != "content"} for item in evidence]
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        task = await _manager_call(
            manager,
            "create_task",
            product["id"],
            "Draft",
            brief="Write release notes",
            project_id=project["id"],
            executor_type="agent",
            executor_id=executor_id,
            evidence=evidence,
        )
    assert task["origin"] == "routine" and task["routine_id"] == routine["id"]
    return task, routine, manager


@pytest.mark.asyncio
async def test_builtin_checks_on_fresh_deployment_and_lifetime_limit(system, tmp_path):
    from agno.company.execution import _call
    from agno.company.routines import _manager_call, _RoutineAuthorization
    from agno.run.authorization import authorization_scope

    client, db, worker, os, _ = system
    assert os.company.acceptance_checks == {}
    task, routine, manager = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    with authorization_scope(lambda: _RoutineAuthorization(None, routine["id"])):
        other = await _manager_call(
            manager,
            "create_task",
            task["product_id"],
            "Other",
            project_id=task["project_id"],
            executor_type="agent",
            executor_id="writer",
            evidence=task["evidence"],
        )
    results = await asyncio.gather(executor._accept(task), executor._accept(other), return_exceptions=True)
    assert sum(isinstance(result, dict) for result in results) == 1, results
    assert any("limit" in str(result) for result in results), results
    ready = next(result for result in results if isinstance(result, dict))
    assert ready["status"] == "ready"
    assert await executor._dispatch(ready)
    assert (await execute(worker))["status"] == "completed"
    # Soft deletion and a restart do not replenish the accepted-work budget.
    assert await _call(db, "delete_task", ready["id"])
    loser = other if ready["id"] == task["id"] else task
    with pytest.raises(ValueError, match="limit"):
        await executor._accept(loser)


@pytest.mark.asyncio
async def test_auto_accept_executor_mismatch_revocation_unknown_and_forged_evidence(system, tmp_path):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path, executor_id="agent-b")
    executor, _ = await automation(system)
    with pytest.raises(ValueError, match="executor"):
        await executor._accept(task)
    task = await _call(db, "update_task", task["id"], executor_id="writer")
    original = task["evidence"]
    task = await _call(db, "update_task", task["id"], evidence=[{**original[0], "content_hash": "agent-asserted"}])
    with pytest.raises(ValueError, match="has_source_evidence"):
        await executor._accept(task)
    task = await _call(db, "update_task", task["id"], evidence=original)
    # Direct scheduler edits must also fail closed at the acceptance boundary.
    row = await _call(db, "get_schedule", routine["id"])
    payload = row["payload"]
    payload["metadata"]["auto_accept"]["required_checks"] = ["not-installed"]
    await _call(db, "update_schedule", routine["id"], payload=payload)
    with pytest.raises(ValueError, match="Unknown"):
        await executor._accept(task)
    assert (await _call(db, "get_task", task["id"]))["status"] == "backlog"
    assert (await client.patch(f"/company/routines/{routine['id']}", json={"auto_accept": False})).status_code == 200
    with pytest.raises(ValueError, match="no human"):
        await executor._accept(task)


@pytest.mark.asyncio
async def test_auto_accept_revocation_after_queue_and_scope_changes_during_check(system, tmp_path):
    from agno.company.execution import _call

    client, db, worker, os, _ = system
    task, routine, _ = await routine_proposal(system, tmp_path)
    executor, _ = await automation(system)
    ready = await executor._accept(task)
    await executor._dispatch(ready)
    assert (await client.patch(f"/company/routines/{routine['id']}", json={"auto_accept": False})).status_code == 200
    with pytest.raises(ValueError, match="revoked"):
        await executor._dispatch(ready)
    assert (await execute(worker))["status"] == "failed"
    assert (await _call(db, "get_task", task["id"]))["status"] != "in_review"
