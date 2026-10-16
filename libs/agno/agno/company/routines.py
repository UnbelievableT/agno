"""Company schedule payloads and bundled Skills; the scheduler owns execution."""

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

from agno.company.declarations import Routine
from agno.company.execution import _call, _ExecutorAuthorization, _validate_executor_tools
from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
from agno.scheduler.executor import ScheduleExecutor
from agno.skills import LocalSkills, Skills


def load_routine_skills() -> Skills:
    """Load the editable, packaged Routine templates through the standard loader."""
    return Skills(loaders=[LocalSkills(str(Path(__file__).parent / "skills"))])


async def aload_routine_skills() -> Skills:
    """Load templates without blocking the event loop."""
    return await asyncio.to_thread(load_routine_skills)


def _schedule_fields(product_id: str, routine: Routine, registry: Any) -> Dict[str, Any]:
    component = getattr(registry, "get_" + routine.executor_type)(routine.executor_id) if registry else None
    if component is None:
        raise ValueError("Routine executor is missing from the registry")
    _validate_executor_tools(component)
    skill = load_routine_skills().get_skill(routine.template)
    if skill is None:
        raise ValueError("Routine template is unavailable")
    endpoint = f"/{routine.executor_type}s/{routine.executor_id}/runs"
    if RUN_ENDPOINT_RE.fullmatch(endpoint) is None:
        raise ValueError("Invalid Routine executor id")
    return dict(
        name=product_id + "." + routine.name,
        cron_expr=routine.cron_expr,
        endpoint=endpoint,
        timezone=routine.timezone,
        payload={
            "message": routine.instructions or skill.instructions,
            "metadata": {"product_id": product_id, "template": routine.template, "auto_accept": False},
        },
    )


class _RoutineAuthorization(_ExecutorAuthorization):
    """Routine authority permits proposals, never acceptance or schedule edits."""

    def __init__(self, original: Any, routine_id: Optional[str] = None):
        super().__init__(original)
        self.routine_id = routine_id

    def snapshot(self) -> Dict[str, Any]:
        return {
            **super().snapshot(),
            "company_routine": True,
            "company_routine_unscoped": self.original is None,
            "company_routine_id": self.routine_id,
        }


async def _authorize_auto_accept(request, policy, agent_os=None):
    from fastapi import HTTPException

    from agno.company.declarations import AutoAccept
    from agno.company.execution import _executor, _ExecutorAuthorization
    from agno.os.routers.run_permissions import _require_endpoint_permission
    from agno.run.authorization import current_authorization

    authority = current_authorization()
    if (
        isinstance(authority, _ExecutorAuthorization)
        or (authority is not None and authority.service_account)
        or getattr(request.state, "is_internal_service", False)
    ):
        raise HTTPException(403, "Only a human may authorize automatic acceptance")
    if authority is not None:
        try:
            await authority.arequire("schedules", "write")
            if policy:
                await authority.arequire("tasks", "write")
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
    if policy:
        try:
            parsed = AutoAccept.model_validate(policy)
            if agent_os is not None:
                _executor(agent_os.registry, parsed.executor_type, parsed.executor_id, accepting=True)
                if any(name not in _acceptance_checks(agent_os) for name in parsed.required_checks):
                    raise ValueError("Unknown automatic acceptance check")
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        await _require_endpoint_permission(
            request, f"/{parsed.executor_type}s/{parsed.executor_id}/runs", "POST", action="accept"
        )


async def _stamp_auto_accept(request, payload):
    from agno.run.authorization import AUTHORIZATION_KEY, authorization_snapshot

    payload = dict(payload or {})
    metadata = dict(payload.get("metadata") or {})
    payload.pop("_agno_company_acceptance", None)
    policy = metadata.get("auto_accept")
    if policy:
        await _authorize_auto_accept(request, policy)
        # Even in an unauthenticated local deployment this marker is generated
        # here, never copied from a supplied payload. Executor snapshots cannot
        # pass the human boundary above.
        payload["_agno_company_acceptance"] = {
            AUTHORIZATION_KEY: authorization_snapshot(),
            "user_id": getattr(request.state, "user_id", None),
        }
    payload["metadata"] = metadata
    return payload


def _policy_fingerprint(schedule):
    import hashlib
    import json

    metadata = (schedule.get("payload") or {}).get("metadata") or {}
    return hashlib.sha256(
        json.dumps(
            {
                "product_id": metadata.get("product_id"),
                "auto_accept": metadata.get("auto_accept"),
                "authority": (schedule.get("payload") or {}).get("_agno_company_acceptance"),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


async def _check_automatic_policy(schedule_db, task):
    receipts = [
        entry["auto_accept"]
        for entry in task.get("transitions", [])
        if entry.get("target") == "ready" and entry.get("auto_accept")
    ]
    # Only the most recent acceptance owns this attempt. A later human
    # acceptance supersedes a Routine's old receipt.
    acceptances = [entry for entry in task.get("transitions", []) if entry.get("target") == "ready"]
    if not receipts or not acceptances[-1].get("auto_accept"):
        return
    receipt = acceptances[-1]["auto_accept"]
    schedule = await _call(schedule_db, "get_schedule", receipt["routine_id"]) if schedule_db else None
    if (
        schedule is None
        or not schedule["enabled"]
        or schedule.get("managed_by") != "company"
        or _policy_fingerprint(schedule) != receipt["policy"]
    ):
        raise ValueError("Routine automatic acceptance was changed or revoked")
    import time

    from agno.company.declarations import AutoAccept

    policy = AutoAccept.model_validate(schedule["payload"]["metadata"]["auto_accept"])
    if policy.limits.expires_at is not None and int(time.time()) >= policy.limits.expires_at:
        raise ValueError("Routine automatic acceptance expired")


async def _manager_call(manager, name, *args, **kwargs):
    import inspect

    fn = getattr(manager, name)
    return (
        await fn(*args, **kwargs) if inspect.iscoroutinefunction(fn) else await asyncio.to_thread(fn, *args, **kwargs)
    )


async def _project_active(task, manager):
    project = await _manager_call(manager, "get_project", task["project_id"]) if task.get("project_id") else None
    return bool(project and project["product_id"] == task["product_id"] and project["status"] == "active")


async def _has_source_evidence(task, manager):
    evidence = task.get("evidence") or []
    if not evidence:
        return False
    for item in evidence:
        if not isinstance(item, dict) or not all(
            item.get(key) for key in ("source_id", "content_hash", "link", "run_id")
        ):
            return False
        source = await _manager_call(manager, "get_source", item["source_id"])
        if not source or source["product_id"] != task["product_id"]:
            return False
        current = await _manager_call(manager, "read_source", item["source_id"], item["run_id"])
        if not any(row["content_hash"] == item["content_hash"] and row["link"] == item["link"] for row in current):
            return False
    return True


async def _executor_registered(task, manager):
    from agno.company.execution import _executor

    _executor(manager.registry, task.get("executor_type"), task.get("executor_id"), accepting=True)
    return True


def _acceptance_checks(agent_os):
    checks = {
        "project_active": _project_active,
        "has_source_evidence": _has_source_evidence,
        "executor_registered": _executor_registered,
    }
    custom = agent_os.company.acceptance_checks
    if set(checks).intersection(custom):
        raise ValueError("Application acceptance checks cannot replace built-in checks")
    return {**checks, **custom}


_AUTOMATION_SCHEDULE_ID = "agno-company-automation"


async def _ensure_automation_schedule(db):
    import time

    from agno.db.schemas.scheduler import Schedule
    from agno.db.utils import is_unique_violation

    existing = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
    if existing is None:
        row = Schedule(
            id=_AUTOMATION_SCHEDULE_ID,
            name="Company automation",
            cron_expr="* * * * *",
            endpoint="/company/attention",
            method="GET",
            managed_by="company",
            next_run_at=int(time.time()),
            created_at=int(time.time()),
        ).to_dict()
        try:
            await _call(db, "create_schedule", row)
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
        existing = await _call(db, "get_schedule", _AUTOMATION_SCHEDULE_ID)
    if existing is None or existing.get("managed_by") != "company" or existing["endpoint"] != "/company/attention":
        raise ValueError("Company automation schedule identity is already in use")
    return existing




class _CompanyScheduleExecutor(ScheduleExecutor):
    """Run the existing scheduler's claimed Company tick, without another loop."""

    def __init__(self, agent_os, app, **kwargs):
        super().__init__(**kwargs)
        self.agent_os = agent_os
        self.app = app

    async def _call_endpoint(self, schedule):
        if schedule.id != _AUTOMATION_SCHEDULE_ID:
            return await super()._call_endpoint(schedule)
        if schedule.managed_by != "company" or schedule.endpoint != "/company/attention" or schedule.method != "GET":
            raise ValueError("Company automation schedule was repointed")
        return {"status": "success", "output": {"tasks": await self._tick()}}

    async def _tick(self):
        db = self.agent_os._company_db
        # Snapshot the candidate ids before mutation so paging cannot skip work.
        tasks: List[Dict[str, Any]] = []
        page = 1
        while True:
            rows, total = await _call(db, "get_tasks", limit=100, page=page)
            tasks.extend(row for row in rows if row["status"] in {"backlog", "ready", "in_progress"})
            if page * 100 >= total:
                break
            page += 1
        outcomes = []
        for candidate in tasks:
            try:
                task = await _call(db, "get_task", candidate["id"])
                if task is None:
                    raise ValueError("Task was deleted")
                if task["status"] == "backlog":
                    if task.get("origin") != "routine" or not task.get("routine_id"):
                        continue
                    task = await self._accept(task)
                if task["status"] not in {"ready", "in_progress"}:
                    raise ValueError("Task is no longer Ready")
                result = await self._dispatch(task)
                outcomes.append({"task_id": task["id"], **result})
            except Exception as exc:
                from fastapi import HTTPException

                reason = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                outcomes.append({"task_id": candidate["id"], "status": "skipped", "reason": reason})
        return outcomes

    async def _accept(self, task):
        import copy
        import inspect
        import time

        from agno.company.declarations import AutoAccept
        from agno.company.execution import _executor
        from agno.company.manager import AsyncCompanyManager, CompanyManager
        from agno.db.base import AsyncBaseDb
        from agno.os.authz.run_context import restore_authorization
        from agno.run.authorization import AUTHORIZATION_KEY, authorization_scope

        os = self.agent_os
        schedule = await _call(os.db, "get_schedule", task["routine_id"])
        if not schedule or not schedule["enabled"] or schedule.get("managed_by") != "company":
            raise ValueError("Routine was disabled or deleted")
        payload = schedule.get("payload") or {}
        metadata = payload.get("metadata") or {}
        grant = payload.get("_agno_company_acceptance")
        if not metadata.get("auto_accept") or grant is None:
            raise ValueError("Routine has no human automatic acceptance authorization")
        policy = AutoAccept.model_validate(metadata["auto_accept"])
        if metadata.get("product_id") != task["product_id"]:
            raise ValueError("Proposal is outside the Routine Product")
        if (task.get("executor_type"), task.get("executor_id")) != (policy.executor_type, policy.executor_id):
            raise ValueError("Proposed executor is outside automatic acceptance authorization")
        scope = policy.work_scope
        if scope and (
            (scope.product_ids is not None and task["product_id"] not in scope.product_ids)
            or (scope.project_ids is not None and task.get("project_id") not in scope.project_ids)
        ):
            raise ValueError("Proposal is outside the authorized work scope")
        if policy.limits.expires_at is not None and int(time.time()) >= policy.limits.expires_at:
            raise ValueError("Routine automatic acceptance expired")
        if policy.source_ids is not None:
            evidence = task.get("evidence") or []
            if not evidence or any(
                not isinstance(item, dict) or item.get("source_id") not in policy.source_ids for item in evidence
            ):
                raise ValueError("Proposal is outside the authorized Sources")
        _executor(os.registry, task["executor_type"], task["executor_id"], accepting=True)
        authority = restore_authorization(self.app, grant.get(AUTHORIZATION_KEY))
        if isinstance(authority, _ExecutorAuthorization) or (authority is not None and authority.service_account):
            raise ValueError("Automatic acceptance requires human authority")
        if authority is None and os.authorization:
            raise ValueError("Automatic acceptance has no saved human authority")
        if authority is not None:
            for resource, action, resource_id in (
                ("schedules", "write", None),
                ("tasks", "write", None),
                (policy.executor_type + "s", "run", policy.executor_id),
            ):
                await authority.arequire(resource, action, resource_id)
        manager = (
            AsyncCompanyManager(os._company_db, os.registry)
            if isinstance(os._company_db, AsyncBaseDb)
            else CompanyManager(os._company_db, os.registry)
        )
        checks = _acceptance_checks(os)
        with authorization_scope(lambda: authority):
            for name in policy.required_checks:
                check = checks.get(name)
                if check is None:
                    raise ValueError("Unknown automatic acceptance check: " + name)
                result = (
                    await check(copy.deepcopy(task), manager)
                    if inspect.iscoroutinefunction(check)
                    else await asyncio.to_thread(check, copy.deepcopy(task), manager)
                )
                if inspect.isawaitable(result):
                    result = await result
                if result is not True:
                    raise ValueError("Required automatic acceptance check failed: " + name)
            # Re-read authorization after potentially slow Source/check work.
            current = await _call(os.db, "get_schedule", schedule["id"])
            if not current or not current["enabled"] or _policy_fingerprint(current) != _policy_fingerprint(schedule):
                raise ValueError("Routine automatic acceptance changed during checks")
            accepted = await _manager_call(
                manager,
                "transition_task",
                task["id"],
                "ready",
                "Authorized Routine proposal",
                accepted_by=grant.get("user_id"),
                executor_type=policy.executor_type,
                executor_id=policy.executor_id,
                expected_task=task,
                auto_accept={
                    "routine_id": schedule["id"],
                    "policy": _policy_fingerprint(schedule),
                    "max_acceptances": policy.limits.max_acceptances,
                },
            )
        if accepted is None:
            raise ValueError("Proposal changed during automatic acceptance")
        return accepted

    async def _dispatch(self, task):
        import json
        from urllib.parse import quote

        import httpx

        from agno.company.execution import _automatic_task, _executor
        from agno.db.schemas.scheduler import SCHEDULE_OWNER_HEADER
        from agno.os.authz.run_context import restore_authorization
        from agno.run.authorization import AUTHORIZATION_HEADER, AUTHORIZATION_KEY

        os = self.agent_os
        acceptances = [entry for entry in task["transitions"] if entry.get("target") == "ready"]
        if not acceptances or AUTHORIZATION_KEY not in acceptances[-1]:
            raise ValueError("Task needs a fresh acceptance before automatic pickup")
        snapshot = acceptances[-1][AUTHORIZATION_KEY]
        authority = restore_authorization(self.app, snapshot)
        if authority is None and os.authorization:
            raise ValueError("Task acceptance has no saved caller authority")
        _executor(os.registry, task.get("executor_type"), task.get("executor_id"))
        if authority is not None:
            await authority.arequire(task["executor_type"] + "s", "run", task["executor_id"])
            await authority.arequire("tasks", "write")
            await authority.arequire("wiki", "read")
        await _check_automatic_policy(os.db, task)
        attempts = [entry["attempt"] for entry in task["transitions"] if entry.get("attempt")]
        attempt = max(attempts, default=0) + (1 if task["status"] == "ready" else 0)
        if attempt < 1:
            raise ValueError("Only Ready Tasks or pending submissions can be picked up")
        if task["status"] == "in_progress":
            queue = getattr(self.app.state, "queue_worker", None)
            if queue is not None and await queue.store.get_job(task["job_id"]) is not None:
                return {"status": "already_submitted", "run_id": task["job_id"]}
        # This is the ordinary manual Task route, which reserves the attempt,
        # checks the registry and run scope, and enters the executor's run route.
        headers = {"Authorization": "Bearer " + self.internal_service_token, AUTHORIZATION_HEADER: json.dumps(snapshot)}
        if task.get("accepted_by") is not None:
            headers[SCHEDULE_OWNER_HEADER] = quote(task["accepted_by"], safe="")
        current = await _call(os._company_db, "get_task", task["id"])
        if current != task:
            raise ValueError("Task acceptance changed before automatic dispatch")
        token = _automatic_task.set(task)
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url=self.base_url) as client:
                response = await client.post(
                    f"/company/tasks/{task['id']}/runs", json={"attempt": attempt}, headers=headers
                )
            if response.status_code != 202:
                raise ValueError(response.text)
            return {"status": "submitted", **response.json()}
        finally:
            _automatic_task.reset(token)
