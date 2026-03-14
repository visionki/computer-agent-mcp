import pytest

from computer_agent_mcp.server import build_arg_parser


def test_arg_parser_supports_shorter_startup_names():
    parser = build_arg_parser()
    args = parser.parse_args(
        [
            "--api-key",
            "sk-test",
            "--base-url",
            "https://example.com/v1",
            "--model",
            "gpt-5.4",
            "--user-agent",
            "Codex Desktop/Test",
        ]
    )
    assert args.openai_api_key == "sk-test"
    assert args.openai_base_url == "https://example.com/v1"
    assert args.openai_model == "gpt-5.4"
    assert args.openai_user_agent == "Codex Desktop/Test"
