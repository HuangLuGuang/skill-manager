from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


WORKER_DIR = Path("services/agent-security-worker").resolve()
if str(WORKER_DIR) not in sys.path:
    sys.path.insert(0, str(WORKER_DIR))

from aig_scan_common import AigScanStopped  # noqa: E402
from llm_redteam_adapter import execute_llm_redteam_scan, normalize_llm_redteam_result  # noqa: E402


def _claim(**options):
    return {
        "task": {"task_id": "asj_llm_test"},
        "target": {
            "endpoint_url": "https://model.example/v1",
            "config": {"model": "target-model", "chat_completions_path": "/v1/chat/completions"},
        },
        "policy": {"task_timeout_seconds": 30, "max_duration_seconds": 30},
        "scan_options": {
            "datasets": ["JailBench-Tiny"],
            "num_prompts": 2,
            "random_seed": 42,
            "techniques": ["Raw"],
            **options,
        },
    }


def _raw_result():
    return {
        "content": [
            {
                "modelName": "target-model",
                "baseTotal": 4,
                "results": [
                    {
                        "status": "Safe",
                        "vulnerability": "Harm",
                        "attackMethod": "Raw",
                        "input": "secret test prompt one",
                        "output": "refused",
                        "reason": "policy refusal",
                    },
                    {
                        "status": "Jailbreak",
                        "vulnerability": "Illegal Activity",
                        "attackMethod": "Roleplay",
                        "input": "secret test prompt two",
                        "output": "unsafe answer",
                        "reason": "unsafe content supplied",
                    },
                    {
                        "status": "Exception",
                        "vulnerability": "PII",
                        "attackMethod": "Raw",
                        "input": "prompt three",
                        "output": None,
                        "error": "evaluator timeout",
                    },
                    {
                        "status": "SimulationFailed",
                        "vulnerability": "Bias",
                        "attackMethod": "Roleplay",
                        "input": "prompt four",
                        "output": None,
                    },
                ],
                "usage": {"target_tokens": 120, "evaluator_tokens": 80},
            }
        ]
    }


def test_llm_normalization_creates_one_case_per_prompt_and_precise_finding():
    result = normalize_llm_redteam_result(
        claim=_claim(), raw_result=_raw_result(), session_id="aig-session-llm", initial_usage={}
    )

    assert [item["status"] for item in result["cases"]] == ["passed", "failed", "error", "unverified"]
    assert len(result["cases"]) == 4
    assert result["findings"][0]["case_external_id"] == "aig-llm-prompt:2"
    assert result["cases"][0]["response_summary"]["assessment_status"] == "attack_resisted"
    assert result["cases"][1]["response_summary"]["assessment_status"] == "jailbreak_signal_detected"
    assert result["cases"][2]["response_summary"]["assessment_status"] == "unverified"
    assert result["usage"]["tokens"] == 200
    metadata = result["artifacts"][0]["metadata"]
    assert metadata["attack_success_rate"] == 0.5
    assert metadata["target_model_tokens"] == 120
    assert metadata["evaluator_model_tokens"] == 80
    assert "secret test prompt two" not in str(result["cases"])
    assert "secret test prompt two" in result["artifacts"][0]["content"]
    assert result["artifacts"][0]["metadata"]["content_encrypted_at_rest"] is True


class _Client:
    def __init__(self, *, resumed=False):
        self.created = []
        self.cancelled = []
        self.resumed = resumed

    def create_task(self, **kwargs):
        self.created.append(kwargs)
        return "aig-session-llm"

    def get_status(self, session_id):
        assert session_id == "existing-session" if self.resumed else "aig-session-llm"
        return {"session_id": session_id, "status": "done"}

    def get_result(self, _session_id):
        return _raw_result()

    def cancel_task(self, session_id):
        self.cancelled.append(session_id)


def test_llm_execute_uses_separate_target_and_evaluator_credentials_and_persists_session():
    client = _Client()
    heartbeats = []

    result = execute_llm_redteam_scan(
        _claim(),
        "target-only-secret",
        SimpleNamespace(api_key="evaluator-only-secret", model="eval-model", base_url="https://gateway/v1"),
        lambda usage, session=None: heartbeats.append((usage, session)) or {"continue_allowed": True},
        initial_usage={"rounds": 22, "tokens": 400, "cost_microunits": 0, "concurrent_requests": 1, "response_bytes": 0},
        client=client,
    )

    content = client.created[0]["content"]
    assert content["model"][0]["token"] == "target-only-secret"
    assert content["eval_model"]["token"] == "evaluator-only-secret"
    assert client.created[0]["idempotency_key"] == "agent-manager:asj_llm_test"
    assert heartbeats[0][1] == "aig-session-llm"
    assert result["session_state"] == "aig-session-llm"
    assert result["usage"]["rounds"] == 24
    assert result["usage"]["tokens"] == 600
    assert "target-only-secret" not in str(result)
    assert "evaluator-only-secret" not in str(result)


def test_llm_retry_resumes_existing_session_without_duplicate_create():
    client = _Client(resumed=True)
    claim = _claim(upstream_session_id="existing-session")
    execute_llm_redteam_scan(
        claim,
        "target-secret",
        SimpleNamespace(api_key="eval-secret", model="eval", base_url="https://gateway/v1"),
        lambda *_args: {"continue_allowed": True},
        initial_usage={},
        client=client,
    )
    assert client.created == []


def test_llm_kill_switch_cancels_real_upstream_session():
    client = _Client()
    with pytest.raises(AigScanStopped):
        execute_llm_redteam_scan(
            _claim(),
            "target-secret",
            SimpleNamespace(api_key="eval-secret", model="eval", base_url="https://gateway/v1"),
            lambda *_args: {"continue_allowed": False, "stop_reason": "kill_switch.activated"},
            initial_usage={},
            client=client,
        )
    assert client.cancelled == ["aig-session-llm"]


def test_llm_invalid_or_empty_report_is_never_reported_as_safe():
    with pytest.raises(Exception, match="llm_result_invalid"):
        normalize_llm_redteam_result(
            claim=_claim(), raw_result={"unexpected": []}, session_id="s", initial_usage={}
        )
