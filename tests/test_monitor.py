from computer_agent_mcp.monitor import SyntheticEventFilter


def test_expect_click_count_consumes_double_click():
    event_filter = SyntheticEventFilter()
    event_filter.expect_click(100, 200, "left", count=2)

    assert event_filter.ignore_click(100, 200, "left") is True
    assert event_filter.ignore_click(100, 200, "left") is True
    assert event_filter.ignore_click(100, 200, "left") is False
