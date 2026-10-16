"""Validated declarations shared by code, YAML and blank-deployment setup."""

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agno.db.schemas.sources import validate_source_fields


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    type: Literal["git", "markdown", "website"]
    reference: str
    credential_ref: Optional[str] = None
    config: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_reader(self):
        validate_source_fields(self.model_dump(exclude={"id"}))
        return self


class AcceptanceScope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    product_ids: Optional[List[str]] = None
    project_ids: Optional[List[Optional[str]]] = None


class AcceptanceLimits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    max_acceptances: int = Field(1, ge=1)
    expires_at: Optional[int] = Field(None, ge=1)


class AutoAccept(BaseModel):
    """Human-authored bounds; identifiers refer to existing records and server checks."""

    model_config = ConfigDict(extra="forbid", strict=True)
    executor_type: Literal["agent", "team", "workflow"]
    executor_id: str = Field(min_length=1)
    source_ids: Optional[List[str]] = None
    work_scope: Optional[AcceptanceScope] = None
    required_checks: List[str] = Field(default_factory=list)
    limits: AcceptanceLimits = Field(default_factory=AcceptanceLimits)


class Routine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=255)
    template: Literal["refresh", "intake", "summary"]
    executor_type: Literal["agent", "team", "workflow"]
    executor_id: str = Field(min_length=1)
    cron_expr: str
    timezone: str = "UTC"
    instructions: Optional[str] = None
    auto_accept: Union[Literal[False], AutoAccept] = False

    @model_validator(mode="after")
    def validate_schedule(self):
        from agno.scheduler.cron import validate_cron_expr, validate_timezone

        if not validate_cron_expr(self.cron_expr):
            raise ValueError("Invalid cron expression")
        if not validate_timezone(self.timezone):
            raise ValueError("Invalid timezone")
        return self


class Product(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    name: str = Field(min_length=1)
    purpose: Optional[str] = None
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    sources: List[Source] = Field(default_factory=list)
    routines: List[Routine] = Field(default_factory=list)
