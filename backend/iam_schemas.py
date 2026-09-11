from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AccountCreate(Input):
    username: str = Field(min_length=1, max_length=64)
    email: EmailStr | None = None
    password: str = Field(min_length=8)
    role: str = "user"
    is_active: bool = True
    group_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("username")
    @classmethod
    def non_blank_username(cls, value):
        if not value.strip():
            raise ValueError("Username cannot be blank")
        return value


class AccountUpdate(Input):
    email: EmailStr | None = None
    role: str | None = None
    is_active: bool | None = None
    group_ids: list[int] | None = None

    @field_validator("role", "is_active", "group_ids")
    @classmethod
    def non_null(cls, value):
        if value is None:
            raise ValueError("Field cannot be null")
        return value


class PasswordReset(Input):
    password: str = Field(min_length=8)


class RoleCreate(Input):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    default_path: str = Field(default="", max_length=256)


class RoleUpdate(Input):
    display_name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=2000)
    default_path: str = Field(default="", max_length=256)


class Grant(Input):
    permissions: list[str] = Field(max_length=500)
    default_path: str = Field(default="", max_length=256)


class MenuUpdate(Input):
    parent_name: str | None = None
    title_zh: str = Field(min_length=1, max_length=128)
    title_en: str = Field(min_length=1, max_length=128)
    icon: str = "setting"
    path: str | None = None
    sort_order: int = Field(default=0, ge=0, le=100000)
    is_active: bool = True


class MenuCreate(MenuUpdate):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$")


class Move(Input):
    direction: Literal["up", "down"]


class Status(Input):
    is_active: bool
