from computer_agent_mcp.config import ServerConfig


def test_config_from_env_parses_limits(monkeypatch):
    monkeypatch.setenv("COMPUTER_AGENT_MAX_STEPS_DEFAULT", "9")
    monkeypatch.setenv("COMPUTER_AGENT_MAX_DURATION_S_DEFAULT", "321")
    monkeypatch.setenv("COMPUTER_AGENT_HUMAN_OVERRIDE", "false")
    config = ServerConfig.from_env()
    assert config.max_steps_default == 9
    assert config.max_duration_s_default == 321
    assert config.human_override_enabled is False


def test_invalid_bool_uses_default(monkeypatch):
    monkeypatch.setenv("COMPUTER_AGENT_HUMAN_OVERRIDE", "ture")
    config = ServerConfig.from_env()
    assert config.human_override_enabled is True


def test_config_defaults_use_openai_official_values(monkeypatch):
    monkeypatch.delenv("COMPUTER_AGENT_OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("COMPUTER_AGENT_OPENAI_MODEL", raising=False)
    monkeypatch.delenv("COMPUTER_AGENT_OPENAI_USER_AGENT", raising=False)
    config = ServerConfig.from_env()
    assert config.openai_base_url == "https://api.openai.com/v1"
    assert config.openai_model == "gpt-5.4"
    assert config.openai_user_agent is None
