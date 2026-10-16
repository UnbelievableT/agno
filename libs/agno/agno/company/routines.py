"""Company schedule payloads and bundled Skills; the scheduler owns execution."""

import asyncio
from pathlib import Path
from typing import Any, Dict

from agno.company.declarations import Routine
from agno.company.execution import _ExecutorAuthorization, _validate_executor_tools
from agno.db.schemas.scheduler import RUN_ENDPOINT_RE
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

    def snapshot(self) -> Dict[str, Any]:
        return {**super().snapshot(), "company_routine": True}
