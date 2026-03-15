from computer_agent_mcp.models import ClickAction, RunResult, TraceStep
from computer_agent_mcp.server import _format_run_result_text, build_arg_parser


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


def test_format_run_result_text_includes_trace():
    text = _format_run_result_text(
        RunResult(
            status="completed",
            summary="已打开目标页面",
            details="页面显示成功结果。",
            run_id="run123",
            steps_executed=2,
            trace=[
                TraceStep(
                    step_index=1,
                    observation="页面上可见搜索框。",
                    summary="点击搜索框",
                    expected_outcome="搜索框将获得焦点。",
                    actions=[ClickAction(x=100, y=80)],
                    execution_status="ok",
                    execution_message="Executed 1 action(s).",
                    resulting_window_title="Search Page",
                    resulting_active_app="Browser",
                ),
                TraceStep(
                    step_index=2,
                    observation="页面显示成功状态。",
                    summary="任务完成",
                    execution_status="completed",
                    resulting_window_title="Search Page",
                    resulting_active_app="Browser",
                ),
            ],
        )
    )
    assert "页面显示成功结果。" in text
    assert "run_id: run123" in text
    assert "steps_executed: 2" in text
    assert "Step 1" in text
    assert "observation: 页面上可见搜索框。" in text
    assert "summary: 点击搜索框" in text
    assert "actions: left click at (100, 80)" in text
    assert "expected_outcome: 搜索框将获得焦点。" in text
    assert "execution_status: ok" in text
    assert "resulting_window_title: Search Page" in text
    assert "summary: 任务完成" in text
