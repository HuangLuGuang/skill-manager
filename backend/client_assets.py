"""Read-only client asset snapshots shared by client and Agent views."""

from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

AssetText = Annotated[str, Field(max_length=2048)]
AssetName = Annotated[str, Field(max_length=512)]


class AssetModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class MCPAsset(AssetModel):
    id: Annotated[str, Field(max_length=128)]
    name: AssetName
    transport: Literal["stdio", "streamable_http", "sse", "registered", "unknown"] = "unknown"
    endpoint_origin: AssetText = ""
    server_reference: AssetName = ""
    executable: AssetName = ""
    argument_count: int = Field(default=0, ge=0, le=100000)
    credential_keys: list[AssetName] = Field(default_factory=list, max_length=128)
    enabled: bool | None = None
    scope: AssetText = "user"
    source_path: AssetText

    @field_validator("endpoint_origin")
    @classmethod
    def origin_only(cls, value: str) -> str:
        try:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.hostname:
                return ""
            host = f"[{parsed.hostname}]" if ":" in parsed.hostname else parsed.hostname
            return f"{parsed.scheme}://{host}" + (f":{parsed.port}" if parsed.port else "")
        except ValueError:
            return ""

    @field_validator("executable")
    @classmethod
    def executable_only(cls, value: str) -> str:
        if any(char in value for char in " \t\r\n;|&=\"'`"):
            return ""
        return value.replace("\\", "/").rsplit("/", 1)[-1]


class PluginSkillAsset(AssetModel):
    name: AssetName
    path: AssetText


class PluginAsset(AssetModel):
    id: Annotated[str, Field(max_length=128)]
    name: AssetName
    version: AssetName = ""
    format: AssetName = "unknown"
    path: AssetText = ""
    source_path: AssetText
    scope: AssetText = "user"
    state: Literal["installed", "configured", "cached", "local"]
    enabled: bool | None = None
    skills: list[PluginSkillAsset] = Field(default_factory=list, max_length=128)
    mcp_servers: list[MCPAsset] = Field(default_factory=list, max_length=128)


class AssetIssue(AssetModel):
    code: Literal["read_failed", "invalid_config", "limit_reached", "outside_package", "plugin_missing", "symlink_skipped"]
    path: AssetText


class ClientAssetInventory(AssetModel):
    version: Literal[1] = 1
    observed_at: Annotated[str, Field(max_length=64)]
    mcp_supported: bool = False
    plugin_supported: bool = False
    mcp_servers: list[MCPAsset] = Field(default_factory=list, max_length=128)
    plugins: list[PluginAsset] = Field(default_factory=list, max_length=128)
    issues: list[AssetIssue] = Field(default_factory=list, max_length=128)


def asset_inventory(capabilities: dict) -> dict | None:
    value = capabilities.get("asset_inventory")
    return ClientAssetInventory.model_validate(value).model_dump(mode="json") if value is not None else None


def inventory_capabilities(capabilities: dict, snapshot: ClientAssetInventory | None) -> dict:
    # Only the typed report field owns the asset snapshot namespace.
    result = {key: value for key, value in capabilities.items() if key != "asset_inventory"}
    if snapshot is not None:
        result["asset_inventory"] = snapshot.model_dump(mode="json")
    return result
