from computer_agent_mcp.platform_windows import WindowsAdapter, _WindowsControlCursorIndicator


def test_control_cursor_assets_exist():
    asset_dir = WindowsAdapter.control_cursor_asset_dir()
    filenames = set(_WindowsControlCursorIndicator.CURSOR_FILE_BY_SYSTEM_ID.values())

    for filename in filenames:
        assert (asset_dir / filename).is_file()
