"""Sources and durable evidence deduplication on all four supported SQL adapters."""

import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text

from agno.agent import Agent
from agno.company import Product, Source
from agno.company.bootstrap import arehydrate_product
from agno.company.manager import AsyncCompanyManager, CompanyManager
from agno.db.base import AsyncBaseDb
from agno.db.postgres import AsyncPostgresDb, PostgresDb
from agno.db.sqlite import AsyncSqliteDb, SqliteDb
from agno.registry import Registry


@pytest_asyncio.fixture(params=["sqlite", "async_sqlite", "postgres", "async_postgres"])
async def heartbeat(request, tmp_path):
    schema = "heartbeat_" + uuid4().hex
    if "postgres" in request.param:
        cls = AsyncPostgresDb if request.param.startswith("async") else PostgresDb
        db = cls(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai", db_schema=schema)
    else:
        cls = AsyncSqliteDb if request.param.startswith("async") else SqliteDb
        db = cls(db_file=str(tmp_path / "heartbeat.db"))
    registry = Registry(agents=[Agent(id="reader", telemetry=False)])
    manager = (
        AsyncCompanyManager(db, registry=registry)
        if isinstance(db, AsyncBaseDb)
        else CompanyManager(db, registry=registry)
    )

    async def call(name, *args, **kwargs):
        fn = getattr(manager, name)
        return (
            await fn(*args, **kwargs)
            if inspect.iscoroutinefunction(fn)
            else await asyncio.to_thread(fn, *args, **kwargs)
        )

    yield db, manager, call
    if isinstance(db, AsyncBaseDb):
        await db.close()
    else:
        db.close()
    if "postgres" in request.param:
        cleanup = PostgresDb(db_url="postgresql+psycopg://ai:ai@localhost:5532/ai")
        with cleanup.db_engine.begin() as conn:
            conn.execute(text('DROP SCHEMA IF EXISTS "' + schema + '" CASCADE'))
        cleanup.close()


@pytest.mark.asyncio
async def test_evidence_repeat_failure_completion_and_product_scope(heartbeat, tmp_path):
    db, manager, call = heartbeat
    path = tmp_path / "release.md"
    path.write_text("# Release\nA new feature.\n")
    product = await call("create", "Docs")
    source = await call("create_source", product["id"], "markdown", str(path), credential_ref="DOCS_TOKEN")
    first = (await call("intake", source["id"], "first-run"))[0]
    assert first["status"] == "backlog"
    assert first["evidence"][0]["run_id"] == "first-run"
    assert first["evidence"][0]["content_hash"]
    repeat = (await call("intake", source["id"], "repeat-run"))[0]
    assert repeat["id"] == first["id"]
    path.unlink()
    with pytest.raises(ValueError):
        await call("intake", source["id"], "failed-run")
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1
    path.write_text("# Release\nA new feature.\n")
    for target in ("ready", "in_progress", "in_review", "done"):
        kwargs = {"executor_type": "agent", "executor_id": "reader"} if target == "ready" else {}
        await call("transition_task", first["id"], target, "human review", **kwargs)
    after = (await call("intake", source["id"], "after-completion"))[0]
    assert after["id"] == first["id"] and after["status"] == "done"
    await call("delete_task", first["id"])
    assert (await call("intake", source["id"], "after-delete"))[0]["id"] == first["id"]
    other = await call("create", "Other")
    second_source = await call("create_source", other["id"], "markdown", str(path))
    assert (await call("intake", second_source["id"], "other-product"))[0]["id"] != first["id"]
    path.write_text("Changed evidence")
    assert (await call("intake", source["id"], "changed"))[0]["id"] != first["id"]


@pytest.mark.asyncio
async def test_source_paging_soft_delete_and_restart(heartbeat, tmp_path):
    db, manager, call = heartbeat
    declaration = Product(name="Declared", sources=[Source(type="markdown", reference=str(tmp_path / "x.md"))])
    first = await arehydrate_product(db, declaration)
    await call("update", first["id"], purpose="Human edit")
    again = await arehydrate_product(db, declaration)
    assert again["purpose"] == "Human edit"
    sources, total = await call("list_sources", product_id=first["id"], limit=1)
    assert total == 1
    assert (await call("list_sources", user_id="other"))[1] == 0
    await call("delete_source", sources[0]["id"])
    assert (await call("list_sources"))[1] == 0
    assert (await call("list_sources", include_deleted=True))[1] == 1
    await arehydrate_product(db, declaration)
    assert (await call("list_sources"))[1] == 0
    await call("restore_source", sources[0]["id"])
    assert (await call("list_sources"))[1] == 1


@pytest.mark.asyncio
async def test_summary_wiki_and_configured_transport(heartbeat, monkeypatch):
    db, manager, call = heartbeat
    delivery = AsyncMock()
    monkeypatch.setattr("agno.company.summary.adeliver_summary", delivery)
    product = await call("create", "Docs", metadata={"summary": {"interface": "slack", "destination": "docs"}})
    result = await call("summarize", product["id"], "summary-run", [SimpleNamespace(type="slack")])
    assert result["delivered"] is True and result["quiet"] is True
    assert "Quiet successful check" in (await call("read_wiki", product["id"], result["path"])).content
    assert delivery.await_count == 1
    await call("summarize", product["id"], "summary-run", [])
    assert delivery.await_count == 1


@pytest.mark.asyncio
async def test_concurrent_evidence_and_routine_linking(heartbeat, tmp_path):
    from agno.company.execution import _call

    db, manager, call = heartbeat
    product = await call("create", "Concurrent", metadata={"human": "keep"})
    path = tmp_path / "race.md"
    path.write_text("Same evidence")
    source = await call("create_source", product["id"], "markdown", str(path))
    # Initialize the shared tables before racing independent transactions.
    await call("intake", source["id"], "seed")
    path.write_text("New evidence")
    results = await asyncio.gather(*(call("intake", source["id"], "run-" + str(i)) for i in range(6)))
    assert len({result[0]["id"] for result in results}) == 1
    assert (await call("list_tasks", product_id=product["id"]))[1] == 2
    await asyncio.gather(*(_call(db, "add_product_routine", product["id"], "schedule-" + str(i)) for i in range(6)))
    metadata = (await call("get", product["id"]))["metadata"]
    assert metadata["human"] == "keep" and len(metadata["routine_ids"]) == 6


@pytest.mark.asyncio
async def test_git_provider_exclusions_and_failed_batch(heartbeat, tmp_path):
    db, manager, call = heartbeat
    root = tmp_path / "repo"
    root.mkdir()
    (root / "readme.md").write_text("Public content")
    (root / ".env").write_text("SECRET=never-in-evidence")
    product = await call("create", "Repository")
    source = await call("create_source", product["id"], "git", str(root))
    evidence = await call("read_source", source["id"], "read")
    assert len(evidence) == 1 and "never-in-evidence" not in str(evidence)
    invalid = await call("create_source", product["id"], "git", str(root), config={"paths": ["readme.md", ".env"]})
    with pytest.raises(ValueError, match="Source read failed"):
        await call("intake", invalid["id"], "failed")
    assert (await call("list_tasks"))[1] == 0
