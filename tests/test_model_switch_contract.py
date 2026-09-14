import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.api_errors import ApiError
from backend.model_switch import CONTRACT, validate_options, contract_for_version, validate_parameter_version, validate_effective_parameters
from backend.model_switch import reported_model_parameters


@pytest.mark.parametrize("capabilities", [[], {"model_config_state": []}, {"model_config_state": "invalid"}, {"model_config_state": {"parameters": []}}])
def test_malformed_reported_parameters_return_stable_error(capabilities):
    with pytest.raises(ApiError) as caught:
        reported_model_parameters(capabilities)
    assert caught.value.code == "client.model_parameters_invalid"


def test_missing_reported_parameters_allow_first_configuration():
    assert reported_model_parameters({}) == {}
    assert reported_model_parameters({"model_config_state": None}) == {}
    assert reported_model_parameters({"model_config_state": {"parameters": {"request_max_retries": 0}}}) == {"request_max_retries": 0}


def test_generated_go_contract_matches_source():
    generated = (Path(__file__).resolve().parents[1] / "scanner/internal/managedclient/model_contract_generated.go").read_text()
    body = json.loads(generated.split("const modelContractJSON = ", 1)[1].strip())
    assert json.loads(body) == CONTRACT


@pytest.mark.parametrize("parameters", [{"temperature": 0.2}, {"timeout_ms": True}, {"timeout_ms": "1000"}, {"timeout_ms": 1}, {"timeout_ms": 1000.1}])
def test_rejects_unsupported_and_invalid_parameters(parameters):
    with pytest.raises(ApiError):
        validate_options("claude-code", parameters)


def test_unset_and_platform_limit():
    assert validate_options("claude-code", {"timeout_ms": None}) == {"parameters": {}}
    with pytest.raises(ApiError):
        validate_options("claude-code", {"max_output_tokens": 1000}, model=SimpleNamespace(max_output_tokens=500))
    assert validate_options("codex", {"request_max_retries": 0})["parameters"] == {"request_max_retries": 0}


def test_revision_and_agent_validation():
    with pytest.raises(ApiError):
        validate_options("codex", {}, "bad")
    with pytest.raises(ApiError):
        validate_options("unknown", {})


@pytest.mark.parametrize("version", [None, "", "0.131.0", "0.132.0-beta.1", "0.133.0"])
def test_unverified_version_cannot_set_parameters_but_can_preserve_them(version):
    spec = contract_for_version("codex", version)
    assert spec["parameters"] == {}
    assert spec["parameter_status"] == "version_unverified"
    validate_parameter_version("codex", {"request_max_retries": None}, version)
    with pytest.raises(ApiError) as caught:
        validate_parameter_version("codex", {"request_max_retries": 0}, version)
    assert caught.value.code == "client.model_parameter_version_unverified"


def test_verified_version_contract_keeps_source_intact():
    contract_for_version("codex", "unknown")
    spec = contract_for_version("codex", "codex-cli 0.132.0")
    assert "request_max_retries" in spec["parameters"]
    validate_parameter_version("codex", {"request_max_retries": 0}, "v0.132.0")


def test_inherited_output_limit_is_checked_and_explicit_value_takes_precedence():
    model = SimpleNamespace(max_output_tokens=512)
    for explicit in ({}, {"max_output_tokens": None}):
        with pytest.raises(ApiError) as caught:
            validate_effective_parameters("claude-code", explicit, {"max_output_tokens": 1024}, model)
        assert caught.value.code == "client.model_output_limit"
    assert validate_effective_parameters("claude-code", {"max_output_tokens": 256}, {"max_output_tokens": 1024}, model) == {"max_output_tokens": 256}
