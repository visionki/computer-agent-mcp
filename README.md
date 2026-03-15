# computer-agent-mcp

A black-box desktop automation MCP server — give it a task, it handles the screenshots, coordinates, and clicks internally, and returns the result.

[![PyPI version](https://img.shields.io/pypi/v/computer-agent-mcp)](https://pypi.org/project/computer-agent-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/computer-agent-mcp)](https://pypi.org/project/computer-agent-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[中文说明](README_CN.md)

<p align="center">
  <video src="https://github.com/user-attachments/assets/1f61fa7e-2166-49ba-94fa-97913fad5bb2" width="720" controls></video>
</p>

## How It Works

Unlike typical computer-use tools that expose raw screenshots to the host agent, `computer-agent-mcp` runs the entire vision loop **server-side**:

1. Captures the current screen
2. Sends the screenshot + task context to an internal vision model
3. Receives observations, action plans, and coordinate mappings
4. Executes actions locally with visible mouse trajectories
5. Repeats until the task is done — then returns a structured result

The host agent never sees a screenshot. It just sends a task and gets back a result.

## Features

- **Task-level API** — one call to complete a desktop task, no multi-turn screenshot protocol
- **Server-side vision loop** — screenshots, coordinate mapping, and action execution all handled internally
- **Human override detection** — stops immediately when a real user touches the keyboard or mouse
- **Step-by-step debug recording** — full event timeline, screenshots, and model request/response logs
- **Works with any OpenAI-compatible vision model** — bring your own endpoint and model

## Quick Start

### Prerequisites

- Windows
- Python >= 3.11
- An OpenAI-compatible API key

### Install & Run

The quickest way to start:

```bash
uvx computer-agent-mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

Or install via pip:

```bash
pip install computer-agent-mcp
computer-agent-mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

### MCP Host Configuration

Add to your MCP client config (e.g. Claude Desktop, Cursor, etc.):

```json
{
  "mcpServers": {
    "computer-agent": {
      "command": "uvx",
      "args": [
        "computer-agent-mcp",
        "--base-url",
        "https://api.openai.com/v1",
        "--model",
        "gpt-5.4"
      ],
      "env": {
        "COMPUTER_AGENT_OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

## Tools

### `computer_use_task`

Run a stateless black-box desktop task.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `task` | *(required)* | Natural language description of what to do |
| `display_id` | `"primary"` | Target display |
| `max_steps` | `30` | Maximum vision-action loop iterations |

Returns structured result with `status` (`completed` / `blocked` / `failed`), `summary`, `result`, `memory`, and `trace`.

### `computer_list_displays`

List available displays. Useful for multi-monitor setups.

## Configuration

All CLI parameters can also be set via environment variables:

| CLI Flag | Env Variable | Default | Description |
|----------|-------------|---------|-------------|
| `--api-key` | `COMPUTER_AGENT_OPENAI_API_KEY` | — | API key (also reads `OPENAI_API_KEY`) |
| `--base-url` | `COMPUTER_AGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API base URL |
| `--model` | `COMPUTER_AGENT_OPENAI_MODEL` | `gpt-5.4` | Vision model to use |
| `--max-steps-default` | `COMPUTER_AGENT_MAX_STEPS_DEFAULT` | `30` | Default max steps per task |
| `--max-duration-s-default` | `COMPUTER_AGENT_MAX_DURATION_S_DEFAULT` | `120` | Default max duration (seconds) |
| `--debug-dir` | `COMPUTER_AGENT_DEBUG_DIR` | `.computer_agent_mcp_debug/` | Debug output directory |
| `--log-level` | `COMPUTER_AGENT_LOG_LEVEL` | `INFO` | Log level |

Enable debug recording with `COMPUTER_AGENT_DEBUG=1`. See [REFERENCE.md](REFERENCE.md) for the full configuration reference and detailed runtime semantics.

## Development

```bash
pip install -e .[dev]
pytest
```

## Platform Support

Currently **Windows only**. The server will start on other platforms but desktop tool calls will fail.

## Contributing

Contributions are welcome! Please open an issue first to discuss what you'd like to change.

## License

[MIT](LICENSE)
