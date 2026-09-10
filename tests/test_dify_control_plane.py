from pathlib import Path

import pytest

from agent_manager.core.dify_control_plane import collect_dify_dsl, collect_dify_dsl_file


FIXTURE = Path("demo/dify-control-plane-poc/example-app.yml")


def test_collects_prompts_tools_and_knowledge_without_prompt_plaintext():
    result = collect_dify_dsl_file(FIXTURE)

    assert result["app"]["mode"] == "advanced-chat"
    assert result["summary"] == {"nodes": 3, "prompts": 2, "tools": 1, "knowledge_bases": 1}
    assert result["tools"][0]["tool_name"] == "search_tickets"
    assert result["knowledge_bases"][0]["dataset_id"] == "dataset-product-docs"
    assert result["collection_semantics"] == "configured_not_runtime_verified"
    assert all("text" not in prompt for prompt in result["prompts"])
    assert all(len(prompt["sha256"]) == 64 for prompt in result["prompts"])


def test_agent_profile_preserves_sources_and_does_not_invent_missing_facts():
    result = collect_dify_dsl_file(FIXTURE)
    profile = result["agent_profile"]

    assert profile["name"] == {
        "value": "Customer support assistant",
        "status": "collected",
        "source": "dsl.app.name",
        "missing_reason": None,
    }
    assert profile["description"]["status"] == "collected"
    assert profile["created_at"]["status"] == "unavailable"
    assert profile["created_at"]["value"] is None
    assert profile["intent"]["status"] == "unverified"
    assert profile["intent"]["value"] is None


def test_prompt_plaintext_requires_explicit_opt_in():
    result = collect_dify_dsl_file(FIXTURE, include_prompt_text=True)

    assert result["prompt_text_included"] is True
    assert result["prompts"][0]["text"] == "Answer only from approved support material."


def test_collects_agent_instruction_and_agent_tool_without_settings_or_secrets():
    document = {
        "app": {"name": "agent", "mode": "agent-chat"},
        "workflow": {
            "graph": {
                "nodes": [
                    {
                        "id": "agent-1",
                        "data": {
                            "type": "agent",
                            "agent_parameters": {
                                "instruction": {"value": "Keep customer data private."},
                                "tools": {
                                    "value": [
                                        {
                                            "enabled": True,
                                            "provider_id": "acme/search",
                                            "tool_name": "search",
                                            "settings": {"api_key": "must-not-be-collected"},
                                        }
                                    ]
                                },
                            },
                        },
                    }
                ]
            }
        },
    }

    result = collect_dify_dsl(document, include_prompt_text=True)

    assert result["prompts"][0]["text"] == "Keep customer data private."
    assert result["tools"][0]["tool_name"] == "search"
    assert "settings" not in result["tools"][0]
    assert "must-not-be-collected" not in str(result)


def test_rejects_non_object_yaml_root():
    with pytest.raises(ValueError, match="root must be an object"):
        collect_dify_dsl(["not", "an", "app"])  # type: ignore[arg-type]
