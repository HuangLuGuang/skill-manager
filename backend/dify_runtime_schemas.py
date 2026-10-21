from typing import Literal
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("host", check_fields=False)
    @classmethod
    def hostname(cls, value):
        try:
            return value.strip().rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            raise ValueError("Invalid hostname") from None

    @field_validator("method", check_fields=False)
    @classmethod
    def method_name(cls, value):
        return value.strip().upper()


class Rule(Strict):
    rule_id: str = Field(min_length=1, max_length=64)
    node_type: str = Field(default="", max_length=64)
    node_id: str = Field(default="", max_length=128)
    tool: str = Field(default="", max_length=256)
    host: str = Field(default="", max_length=253)
    method: str = Field(default="", max_length=16)
    dataset: str = Field(default="", max_length=128)
    code_digest: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    after_node_type: str = Field(default="", max_length=64)
    effect: Literal["allow", "deny", "approval"] = "deny"


class Policy(Strict):
    default: Literal["allow", "deny"] = "allow"
    approved_graphs: list[str] = Field(default_factory=list, max_length=100)
    rules: list[Rule] = Field(default_factory=list, max_length=100)
    approval_seconds: int = Field(default=120, ge=10, le=300)
    max_actions: int = Field(default=500, ge=1, le=10000)

    @field_validator("approved_graphs")
    @classmethod
    def hashes(cls, values):
        if any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x) for x in values):
            raise ValueError("Expected SHA-256 digests")
        return values

    @field_validator("rules")
    @classmethod
    def unique_rules(cls, values):
        if len({r.rule_id for r in values}) != len(values):
            raise ValueError("Duplicate rule ID")
        return values


class BindingCreate(Strict):
    target_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=128)
    instance_id: str = Field(min_length=1, max_length=128)


class PolicyUpdate(Strict):
    revision: int = Field(ge=1)
    mode: Literal["observe", "enforce", "disabled"]
    policy: Policy


class RunStart(Strict):
    run_id: str = Field(min_length=1, max_length=128)
    workspace_id: str = Field(min_length=1, max_length=128)
    app_id: str = Field(min_length=1, max_length=128)
    workflow_id: str = Field(min_length=1, max_length=128)
    graph_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Call(Strict):
    call_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    node_type: str = Field(min_length=1, max_length=64)
    tool: str = Field(default="", max_length=256)
    host: str = Field(default="", max_length=253)
    method: str = Field(default="", max_length=16)
    dataset: str = Field(default="", max_length=128)
    datasets: list[str] = Field(default_factory=list, max_length=100)
    code_digest: str = Field(default="", pattern=r"^([a-f0-9]{64})?$")
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Consume(Strict):
    authorization_token: str = Field(min_length=1, max_length=256)
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class Result(Strict):
    status: Literal["succeeded", "failed", "cancelled"]
    duration_ms: float = Field(ge=0)


class Review(Strict):
    approve: bool


class Heartbeat(Strict):
    process_id: str = Field(min_length=1, max_length=128)
    dify_version: str = Field(min_length=1, max_length=64)
    adapter_version: str = Field(min_length=1, max_length=64)
    hooks: dict[str, bool] = Field(max_length=32)
    queued_events: int = Field(ge=0)


class Observation(Strict):
    run: RunStart
    event_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    event_time: datetime
    node_id: str = Field(min_length=1, max_length=128)
    execution_id: str = Field(min_length=1, max_length=128)
    node_type: str = Field(min_length=1, max_length=64)
    type: Literal["step.start", "step.end", "model.request", "model.response", "model.error", "turn.end"]
    status: Literal["started", "succeeded", "failed", "cancelled", "blocked"]
