from datetime import datetime, timezone
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .security_scan_controls import AGENT_SCAN_SKILLS


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["workspace", "selected"] = "selected"
    app_ids: list[str] = Field(default_factory=list, max_length=1000)
    schedule_kind: Literal["interval", "daily", "cron"] = "interval"
    timezone: str = "Asia/Shanghai"
    interval_minutes: int = Field(default=360, ge=5, le=525600)
    daily_time: str = "02:00"
    cron: str = "0 2 * * *"
    enabled: bool = True
    auto_scan_policy_id: str | None = None
    evaluation_model: str | None = Field(default=None, max_length=128)
    scan_new_apps: bool = True
    scan_changed_apps: bool = True
    skills: list[str] = Field(default_factory=lambda: list(AGENT_SCAN_SKILLS), min_length=1, max_length=10)
    validity_hours: int = Field(default=168, ge=1, le=8760)
    language: Literal["zh", "en"] = "zh"

    @model_validator(mode="after")
    def validate_config(self):
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("invalid IANA timezone") from exc
        if len(set(self.app_ids)) != len(self.app_ids) or any(not x.strip() or len(x) > 128 for x in self.app_ids):
            raise ValueError("invalid or duplicate app ID")
        if self.scope == "selected" and not self.app_ids:
            raise ValueError("selected scope requires app IDs")
        if len(set(self.skills)) != len(self.skills) or any(x not in AGENT_SCAN_SKILLS for x in self.skills):
            raise ValueError("invalid or duplicate scan skill")
        if self.schedule_kind == "daily":
            try:
                datetime.strptime(self.daily_time, "%H:%M")
            except ValueError as exc:
                raise ValueError("invalid daily time") from exc
        if self.schedule_kind == "cron":
            if len(self.cron.split()) != 5 or not croniter.is_valid(self.cron):
                raise ValueError("a valid five-field cron is required")
            # Every-minute schedules are supported; the dispatcher coalesces missed runs.
            croniter(self.cron, datetime.now(timezone.utc)).get_next(datetime)
        return self


class SourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    template_target_id: str = Field(min_length=1, max_length=64)
    policy_id: str = Field(min_length=1, max_length=64)
    config: SourceConfig


class SourceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    policy_id: str = Field(min_length=1, max_length=64)
    config: SourceConfig


class RunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=96)


class IssueReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["open", "accepted", "false_positive", "pending_verification", "resolved"]
    comment: str = Field(min_length=1, max_length=2000)
    closure_task_id: str | None = Field(default=None, max_length=64)


class AssetLinksUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_ids: list[str] = Field(default_factory=list, max_length=50)
