# computer-agent-mcp

一个黑盒桌面自动化 MCP 服务器 — 给它一个任务，它在内部完成截图、坐标换算和操作，返回结果。

[![PyPI version](https://img.shields.io/pypi/v/computer-agent-mcp)](https://pypi.org/project/computer-agent-mcp/)
[![Python](https://img.shields.io/pypi/pyversions/computer-agent-mcp)](https://pypi.org/project/computer-agent-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

[English](README.md)

<p align="center">
  <video src="https://github.com/visionki/computer-agent-mcp/raw/main/.github/assets/demo.mp4" width="720" controls></video>
</p>

## 工作原理

与把截图暴露给主 Agent 的方案不同，`computer-agent-mcp` 在**服务端内部**完成整个视觉循环：

1. 捕获当前桌面截图
2. 将截图 + 任务上下文发给内部视觉模型
3. 模型返回观察、动作计划和坐标映射
4. 在本地执行动作（带可见鼠标轨迹）
5. 循环直到任务完成，返回结构化结果

主 Agent 不会看到任何截图，只需发送任务、接收结果。

## 特性

- **任务级 API** — 一次调用完成桌面任务，无需多轮截图协议
- **服务端视觉循环** — 截图、坐标换算、动作执行全在内部完成
- **人工接管检测** — 用户触碰键鼠时立即停止
- **逐步调试记录** — 完整事件时间线、截图和模型请求/响应日志
- **兼容任意 OpenAI 接口的视觉模型** — 自带 endpoint 和模型即可

## 快速开始

### 环境要求

- Windows
- Python >= 3.11
- OpenAI 兼容接口的 API key

### 安装与运行

最快的启动方式：

```bash
uvx computer-agent-mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

也可以通过 pip 安装：

```bash
pip install computer-agent-mcp
computer-agent-mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

### MCP Host 配置

添加到你的 MCP 客户端配置中（如 Claude Desktop、Cursor 等）：

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

## 工具

### `computer_use_task`

运行一个无状态黑盒桌面任务。

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `task` | *（必填）* | 自然语言任务描述 |
| `display_id` | `"primary"` | 目标显示器 |
| `max_steps` | `30` | 最大视觉-动作循环次数 |

返回结构化结果，包含 `status`（`completed` / `blocked` / `failed`）、`summary`、`result`、`memory` 和 `trace`。

### `computer_list_displays`

列出可用显示器，适用于多显示器环境。

## 配置

所有 CLI 参数都可通过环境变量设置：

| CLI 参数 | 环境变量 | 默认值 | 说明 |
|----------|---------|--------|------|
| `--api-key` | `COMPUTER_AGENT_OPENAI_API_KEY` | — | API key（也读取 `OPENAI_API_KEY`） |
| `--base-url` | `COMPUTER_AGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | API 基础 URL |
| `--model` | `COMPUTER_AGENT_OPENAI_MODEL` | `gpt-5.4` | 使用的视觉模型 |
| `--max-steps-default` | `COMPUTER_AGENT_MAX_STEPS_DEFAULT` | `30` | 默认最大步数 |
| `--max-duration-s-default` | `COMPUTER_AGENT_MAX_DURATION_S_DEFAULT` | `120` | 默认最长持续时间（秒） |
| `--debug-dir` | `COMPUTER_AGENT_DEBUG_DIR` | `.computer_agent_mcp_debug/` | 调试输出目录 |
| `--log-level` | `COMPUTER_AGENT_LOG_LEVEL` | `INFO` | 日志级别 |

设置 `COMPUTER_AGENT_DEBUG=1` 启用调试记录。完整配置和详细运行语义参见 [REFERENCE.md](REFERENCE.md)。

## 开发

```bash
pip install -e .[dev]
pytest
```

## 平台支持

当前仅支持 **Windows**。其他平台可以启动服务，但桌面工具调用会失败。

## 贡献

欢迎贡献！请先开 issue 讨论你想修改的内容。

## 许可证

[MIT](LICENSE)
