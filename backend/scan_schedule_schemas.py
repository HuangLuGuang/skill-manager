from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .security_scan_schemas import SecurityTaskPlanRequest


class ScanTiming(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["interval", "daily", "weekly", "cron"] = "daily"
    timezone: str = "Asia/Shanghai"
    interval_minutes: int = Field(default=360, ge=5, le=525600)
    time: str = "02:00"
    weekday: int = Field(default=1, ge=0, le=6)
    cron: str = "0 2 * * *"

    @model_validator(mode="after")
    def validate_timing(self):
        try:
            ZoneInfo(self.timezone)
            datetime.strptime(self.time, "%H:%M")
        except (KeyError, ValueError) as exc:
            raise ValueError("invalid timezone or time") from exc
        if self.kind == "cron" and (len(self.cron.split()) != 5 or not croniter.is_valid(self.cron)):
            raise ValueError("invalid five-field cron")
        if self.kind == "cron":
            croniter(self.cron, datetime.now(ZoneInfo(self.timezone))).get_next(datetime)
        return self


class ScanScheduleCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=128)
    task: SecurityTaskPlanRequest
    timing: ScanTiming
    enabled: bool = True
    run_immediately: bool = False
    idempotency_key: str = Field(min_length=8, max_length=96)


class ScanScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)
    timing: ScanTiming
    enabled: bool
    task: SecurityTaskPlanRequest | None = None
