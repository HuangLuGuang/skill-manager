"""Desktop menu configuration shared by policy writes and client receipts."""
from typing import Annotated

from pydantic import BeforeValidator

from .api_errors import ApiError

DEFAULT_MENUS = dict.fromkeys(("discover", "models", "records", "runtime-governance"), True)


def validate_menus(value):
    if not isinstance(value, dict) or any(key not in DEFAULT_MENUS or type(item) is not bool for key, item in value.items()):
        raise ApiError(422, "client.desktop_menu_invalid", "菜单配置必须使用支持的菜单标识和布尔值", "Menu configuration requires supported menu IDs and boolean values")
    return value


MenuVisibility = Annotated[dict[str, bool], BeforeValidator(validate_menus)]
