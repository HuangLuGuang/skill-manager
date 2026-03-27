from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserBase(BaseModel):
    username: str
    email: Optional[EmailStr] = None


class UserCreate(UserBase):
    password: str
    role: str = "admin"

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("密码长度至少8位")
        return value


class User(UserBase):
    id: int
    is_active: bool
    role: str
    created_at: datetime
    last_login_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class Token(BaseModel):
    access_token: str
    token_type: str


class TokenData(BaseModel):
    username: Optional[str] = None


class PasswordChange(BaseModel):
    old_password: str
    new_password: str


class LoginLog(BaseModel):
    id: int
    username: str
    ip_address: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class OperationLog(BaseModel):
    id: int
    username: str
    action: str
    target: str
    details: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class LogParseConfigUpdate(BaseModel):
    tenant: str = "default"
    normalize_fields: list[str] = []
    header_fields: list[str] = []
    body_fields: list[str] = []
    computed_fields: list[str] = []
    fields: list[str] = []
    phone_no_field: list[str] = []
    phone_no_field_pos: str = "body"
    static_resource_extensions: list[str] = []
    botgate_log_prefix: str = "botgate_access.log-"


class ModelConfigUpdate(BaseModel):
    uid_parse_error_filter: bool = False
    timestamp_format: str = "dd/MMM/yyyy:HH:mm:ss Z"
    rate_sess_min_req_count: int = 50
    rate_sess_gap: int = 60
    contamination: float = 0
    num_estimators: int = 100
    max_samples: int = 256
    outlier_score: float = 0.65
    micro_sess_gap: int = 5
    micro_sess_max_unq_api_count: int = 20
    sess_api_sim_thresh: float = 0.5
    group_sess_min_count: int = 30
    freq_count: int = 20
    data_sample: float = 0.9
    data_count: int = 30000
    time_series_window_size: int = 600
    window_count: int = 5
    cluster_K: int = 20
    eps: float = 0.1
    min_samples: int = 10
    ts_cluster_group_cnt_thresh: int = 9


class ScheduledTaskBase(BaseModel):
    display_name: str
    description: Optional[str] = None
    task_type: str = "function"
    cron_expr: Optional[str] = None
    enabled: bool = True


class ScheduledTaskCreate(ScheduledTaskBase):
    name: str
    task_func: Optional[str] = None
    command: Optional[str] = None


class ScheduledTaskUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    task_type: Optional[str] = None
    task_func: Optional[str] = None
    command: Optional[str] = None
    cron_expr: Optional[str] = None
    enabled: Optional[bool] = None


class ScheduledTaskResponse(ScheduledTaskBase):
    id: int
    name: str
    task_func: Optional[str] = None
    command: Optional[str] = None
    last_run_at: Optional[datetime] = None
    next_run_at: Optional[datetime] = None
    created_at: datetime
    latest_execution_status: Optional[str] = None


class TaskExecutionResponse(BaseModel):
    id: int
    task_id: int
    task_name: str
    status: str
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    logs: Optional[str] = None
    error: Optional[str] = None

    class Config:
        from_attributes = True


class ExecutionLogsResponse(BaseModel):
    logs: str
    total_lines: int
    has_more: bool


class StatsBackfillRequest(BaseModel):
    days: int = Field(default=7, ge=1, le=90)
    business_name: Optional[str] = None
