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
    proposal = dict(
        title="Document the API",
        brief="Explain the released capability",
        proposal_key="api-docs",
        evidence_links=[path.as_uri()],
    )
    first = await call("intake", source["id"], "first-run", proposal)
    assert first["title"] == proposal["title"] and first["brief"] == proposal["brief"]
    assert "content" not in first["evidence"][0]
    assert first["status"] == "backlog"
    assert first["evidence"][0]["run_id"] == "first-run"
    assert first["evidence"][0]["content_hash"]
    repeat = await call("intake", source["id"], "repeat-run", proposal)
    assert repeat["id"] == first["id"]
    (tmp_path / "unrelated.md").write_text("A sibling is not the configured Source")
    path.unlink()
    with pytest.raises(ValueError, match="Source root is unavailable"):
        await call("intake", source["id"], "failed-run", proposal)
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1
    path.write_text("# Release\nA new feature.\n")
    for target in ("ready", "in_progress", "in_review", "done"):
        kwargs = {"executor_type": "agent", "executor_id": "reader"} if target == "ready" else {}
        await call("transition_task", first["id"], target, "human review", **kwargs)
    after = await call("intake", source["id"], "after-completion", proposal)
    assert after["id"] == first["id"] and after["status"] == "done"
    await call("delete_task", first["id"])
    assert (await call("intake", source["id"], "after-delete", proposal))["id"] == first["id"]
    other = await call("create", "Other")
    second_source = await call("create_source", other["id"], "markdown", str(path))
    assert (await call("intake", second_source["id"], "other-product", proposal))["id"] != first["id"]
    path.write_text("Changed evidence")
    assert (await call("intake", source["id"], "changed", proposal))["id"] == first["id"]
    with pytest.raises(ValueError, match="Proposal evidence"):
        await call("intake", source["id"], "forged", {**proposal, "evidence_links": ["https://unread.test"]})


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
async def test_setup_rechecks_owner_after_concurrent_product_insert(heartbeat, tmp_path, monkeypatch):
    db, _, call = heartbeat
    original = db.create_product
    winner = Product(id="company-setup", name="First owner", user_id="alice")

    async def raced(data):
        # Another setup request wins between our empty read and insert.
        monkeypatch.setattr(db, "create_product", original)
        await arehydrate_product(db, winner)
        return await original(data)

    def raced_sync(data):
        monkeypatch.setattr(db, "create_product", original)
        original({**data, "user_id": "alice"})
        return original(data)

    monkeypatch.setattr(db, "create_product", raced if isinstance(db, AsyncBaseDb) else raced_sync)
    loser = Product(
        id="company-setup",
        name="Other owner",
        user_id="bob",
        sources=[Source(type="markdown", reference=str(tmp_path / "private.md"))],
    )
    with pytest.raises(PermissionError):
        await arehydrate_product(db, loser, scoped_user_id="bob")
    assert (await call("list_sources"))[1] == 0


def test_website_uses_existing_reader_and_hashes_extracted_content(monkeypatch):
    import httpx

    from agno.company.sources import read_source
    from agno.utils.string import hash_string_sha256

    requested = []

    def page(url, **kwargs):
        requested.append((url, kwargs))
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            text="<nav>Navigation</nav><main>Released API</main><a href='/other'>Next</a>",
        )

    monkeypatch.setattr("httpx.get", page)
    monkeypatch.setattr("agno.knowledge.reader.website_reader.WebsiteReader.delay", lambda self: None)
    monkeypatch.setenv("DOCS_SECRET", "must-not-leave-diagnostics")
    source = dict(id="web", type="website", reference="https://docs.example.test/release", credential_ref="DOCS_SECRET")
    evidence = read_source(source, "web-run")
    assert evidence[0]["content"] == "Released API"
    assert evidence[0]["content_hash"] == hash_string_sha256("Released API")
    assert evidence[0]["run_id"] == "web-run"
    assert evidence[0]["link"] == source["reference"]
    assert len(requested) == 1 and "must-not-leave-diagnostics" not in str(requested)


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
    again = await call("summarize", product["id"], "second-summary", [])
    assert again["path"] == result["path"] == "summary.md"
    assert delivery.await_count == 2
    await call("summarize", product["id"], "summary-run", [])
    assert delivery.await_count == 2
    delivery.side_effect = RuntimeError("Transport unavailable")
    with pytest.raises(RuntimeError, match="Transport unavailable"):
        await call("summarize", product["id"], "retry-summary", [])
    delivery.side_effect = None
    await call("summarize", product["id"], "retry-summary", [])
    assert delivery.await_count == 4


@pytest.mark.asyncio
async def test_concurrent_evidence_and_routine_linking(heartbeat, tmp_path):
    from agno.company.execution import _call

    db, manager, call = heartbeat
    product = await call("create", "Concurrent", metadata={"human": "keep"})
    path = tmp_path / "race.md"
    path.write_text("Same evidence")
    source = await call("create_source", product["id"], "markdown", str(path))
    # Initialize the shared tables before racing independent transactions.
    proposal = dict(title="Fix API docs", brief="Describe the API", proposal_key="seed", evidence_links=[path.as_uri()])
    await call("intake", source["id"], "seed", proposal)
    proposal["proposal_key"] = "another-issue"
    path.write_text("New evidence")
    results = await asyncio.gather(*(call("intake", source["id"], "run-" + str(i), proposal) for i in range(6)))
    assert len({result["id"] for result in results}) == 1
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
    (root / "image.png").write_bytes(b"\x89PNG\xff")
    (root / "large.txt").write_text("x\n" * 100001)
    evidence = await call("read_source", source["id"], "mixed")
    assert len(evidence) == 1
    assert set(evidence[0]["skipped_paths"]) == {"image.png", "large.txt"}
    selected = await call("create_source", product["id"], "git", str(root), config={"paths": ["image.png"]})
    with pytest.raises(ValueError, match="Source read failed"):
        await call("read_source", selected["id"], "explicit")
    invalid = await call("create_source", product["id"], "git", str(root), config={"paths": ["readme.md", ".env"]})
    with pytest.raises(ValueError, match="Source read failed"):
        await call(
            "intake",
            invalid["id"],
            "failed",
            dict(
                title="Proposal",
                brief="Never persisted",
                proposal_key="invalid",
                evidence_links=[(root / "readme.md").as_uri()],
            ),
        )
    assert (await call("list_tasks"))[1] == 0


@pytest.mark.asyncio
async def test_intake_requires_a_decision_and_only_stores_selected_evidence(heartbeat, tmp_path):
    _, _, call = heartbeat
    root = tmp_path / "docs"
    root.mkdir()
    for index in range(5):
        (root / (str(index) + ".md")).write_text("External business data " + str(index))
    product = await call("create", "Selective intake")
    source = await call("create_source", product["id"], "git", str(root))
    evidence = await call("read_source", source["id"], "scan")
    assert len(evidence) == 5 and (await call("list_tasks", product_id=product["id"]))[1] == 0
    proposal = dict(
        title="Fix the release guide",
        brief="Explain the newly released options",
        proposal_key="release-options",
        evidence_links=[evidence[0]["link"], evidence[1]["link"]],
    )
    task = await call("intake", source["id"], "proposal", proposal)
    assert len(task["evidence"]) == 2
    assert "External business data" not in str(task)
    (root / "0.md").write_text("Changed business data")
    await call("read_source", source["id"], "next-scan")
    assert (await call("list_tasks", product_id=product["id"]))[1] == 1
    repeated = await call("intake", source["id"], "again", {**proposal, "title": "Clarify the guide"})
    assert repeated["id"] == task["id"]
