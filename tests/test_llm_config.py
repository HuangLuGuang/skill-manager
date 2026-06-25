from agent_manager.core.llm import LLMConfig


def test_model_gateway_llm_config_is_ready_without_api_key():
    config = LLMConfig(
        enabled=True,
        provider="model-gateway",
        api_base="",
        api_key=None,
        model="deepseek-chat",
    )

    assert config.is_ready
    public = config.public_dict()
    assert public["api_key_configured"] is False
