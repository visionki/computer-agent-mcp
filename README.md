# computer-agent-mcp

一个面向通用 MCP host 的黑盒桌面任务 MCP。

它会在服务端内部完成整套桌面自动化循环：

1. 捕获当前桌面截图
2. 把任务、近期轨迹、累计记忆和最新截图发给内部视觉模型
3. 让模型返回观察、记忆增量、动作计划、期望结果和它实际使用的画面尺寸
4. 按模型声明尺寸与真实截图尺寸做坐标换算
5. 在本地执行动作并继续下一轮
6. 对外只返回任务级结果，不把截图暴露给外部主 Agent

这不是官方 `computer use` 的直接封装，而是一个更偏工程化的黑盒视觉执行器。

## 项目定位

这个项目当前的目标很明确：

- 面向通用 MCP host 提供一个可直接调用的桌面任务工具
- 把截图、坐标换算、执行循环、短期 history 和 run 内 memory 都收回服务端
- 对外提供无状态 task API，而不是暴露逐帧截图协议

当前实现范围：

- 仅支持 Windows
- 当前入口为 stdio MCP server
- 对外是无状态 task tool
- 每次调用都必须完整描述任务
- 不提供 `resume` / `continuation_token`
- 新任务会抢占旧任务
- 单次 run 内维护 `memory` 和 `trace`，但不会跨调用持久化

更详细的设计取舍、实验结论和外部参考见 [REFERENCE.md](./REFERENCE.md)。

## 为什么这样做

这个项目没有直接把“主 Agent 看图 + MCP 只执行动作”作为默认路线，主要是因为现实兼容性问题：

- 不同 host 对图片桥接和图片结果消费能力并不稳定
- 不同 provider 的原生 `computer` 或视觉路径坐标系不一定一致
- 多轮截图直接堆进主上下文，体积和控制复杂度都很高

因此当前实现选择：

- 内部使用 `Responses API + message + vision`
- 对外保持任务级黑盒接口
- 由服务端自己负责截图、坐标换算、动作执行、短期轨迹和调试记录

## 快速开始

### 运行环境

- Windows
- Python `>=3.11`
- OpenAI 兼容接口可用的 API key

推荐通过环境变量提供 key：

- `COMPUTER_AGENT_OPENAI_API_KEY`
- `OPENAI_API_KEY`

### 直接运行已发布包

推荐直接通过 `uvx` 启动：

```bash
uvx computer-agent-mcp \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

也可以直接安装已发布包：

```bash
pip install computer-agent-mcp
computer-agent-mcp \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

如果你需要给上游显式发送 `User-Agent`，可以二选一：

- 启动参数：`--user-agent`
- 环境变量：`COMPUTER_AGENT_OPENAI_USER_AGENT`

### 从源码运行

```bash
pip install -e .
python -m computer_agent_mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4
```

## MCP Host 配置示例

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

如果你是本地源码开发，也可以把 `command` 换成 Python，并直接运行模块入口。

## 对外工具

### `computer_list_displays`

列出可用显示器。

适合：

- 多显示器环境
- 需要显式选择非主屏

大多数情况下直接使用默认 `display_id="primary"` 即可。

### `computer_use_task`

运行一个无状态黑盒桌面任务。

输入：

- `task`
- `display_id`，默认 `primary`
- `max_steps`，可选

返回的核心字段：

- `status`
  - `completed`
  - `blocked`
  - `failed`
- `summary`
- `result`
- `run_id`
- `steps_executed`
- `block_reason`
- `next_user_action`
- `warnings[]`
- `memory[]`
- `trace[]`

结果会同时放在：

- `structuredContent`
  - 完整 JSON
- `content`
  - 人类可读摘要

其中：

- `summary`
  - 简短结果或本轮最终结论
- `result`
  - 更完整的最终交付内容
- `memory`
  - 单次 run 内累计得到的任务相关信息
  - 例如标题、候选项、页面要点、分步收集的评论原文
- `trace`
  - 按时间线记录每一轮的观察、记忆增量、意图、动作、期望结果和执行结果
- `next_user_action`
  - 仅在 `blocked` 时使用，告诉人类下一步该做什么

## 运行语义

### 无状态

这是一个无状态接口：

- 每次调用都会从“当前桌面”重新开始
- 服务端不会跨调用保留截图、history 或 memory
- 如果上一次被打断，外部需要根据当前画面重新完整描述任务

但在单次 run 内，服务端会维护两类内部状态：

- `history`
  - 近期执行轨迹，帮助模型感知刚刚做过什么
- `memory`
  - 本轮过程中累计得到的重要信息
  - 每轮模型只返回新增的 `memory_update`
  - 服务端负责追加并在下一轮继续带回模型

### 新任务抢占旧任务

当前同时只允许一个活动任务：

- 如果新任务进来，会向旧任务发送取消信号
- 旧任务以 `superseded` 结束
- 新任务接管执行

### 运行中 progress

长任务执行期间，服务端会持续发送 MCP `notifications/progress`。

典型消息包括：

- `Capturing current screen`
- `Requesting vision worker for step 1`
- `Still waiting for vision worker for step 1`
- `Step 1 action 1/2: wait 1500ms`
- `Capturing updated screen after step 1`
- `Finished`

### 人工优先

如果本地用户真实介入键盘或鼠标：

- 当前执行会停止
- 任务返回 `blocked`
- `block_reason` 为 `human_override`

外部调用方不应无条件自动重试，而应先询问用户为什么介入、当前画面是否仍可继续，再决定是否重新调用。

### 批量动作

模型单轮可以返回多个动作，服务端会顺序执行。

当前策略是：

- 任一动作失败、超时、被人工打断或被新任务抢占时，后续动作不再执行
- 批次执行完后再重新截图进入下一轮
- 当任务依赖中间画面的读取、收集、比较或验证时，会提示模型优先采用更小的动作批次，避免跳过有信息价值的中间状态

## 坐标、截图与本地控制

当前实现不主动缩小截图后再发给模型，而是：

- 发送当前截图原图
- 要求模型显式返回 `image_width` 和 `image_height`
- 服务端根据模型声明尺寸和真实截图尺寸做等比换算

另外还有几条运行约束：

- 发给模型的是原始截图，不额外叠加鼠标准心
- debug 保存的截图可以单独叠加准心辅助排查
- Windows 默认会在单次 run 期间临时切换系统鼠标样式，用来提示“AI 正在控制”
- run 结束后会自动恢复当前用户的光标方案
- 如需关闭该本地提示，可设置 `COMPUTER_AGENT_CONTROL_CURSOR=false`
- 控制光标初始化、资源加载或恢复失败不会中断任务，只会写入 `warnings`
- 任何会触发鼠标定位的动作都会先以可见轨迹将指针移动到目标位置，再执行对应动作

## 内部动作语义

当前内部动作包括：

- `move`
- `click`
- `double_click`
- `right_click`
- `drag`
- `scroll`
- `type`
- `keypress`
- `wait`

补充说明：

- `scroll` 使用语义化方向
  - `direction="down"` 表示向后滚动到更靠后的内容
  - `direction="up"` 表示回到更靠前的内容
- `type` 会受最大字符数限制
- `wait`、`type` 和鼠标动作执行过程中都会检查人工接管、新任务抢占、kill switch 和总任务 deadline

## 阻塞与失败

当前阻塞或失败通常来自：

- 模型返回 `blocked`
- 人工接管
- 超时
- kill switch
- 执行器错误
- 新任务抢占

常见 `block_reason` 包括：

- `human_override`
- `timeout`
- `superseded`
- `environment_error`
- `ambiguous`
- 以及模型自己返回的其他阻塞原因

## 调试

启用调试后会生成 run 级调试记录：

- `.computer_agent_mcp_debug/<run_id>/`

常见内容包括：

- `events.jsonl`
  - 全量事件时间线，也会记录 progress 序列
- `task.txt`
  - 原始任务描述
- `run_config.json`
  - 本轮运行配置摘要
- `result.json`
  - 最终结果，包含 `result`、累计 `memory` 和 `trace`
- `step_XX_request.json`
  - 发给模型的该轮请求摘要
- `step_XX_response.json`
  - 该轮模型响应摘要
- `images/`
  - 原始截图和动作覆盖图

常用调试开关：

- `COMPUTER_AGENT_DEBUG=1`
  - 启用 debug 记录
- `COMPUTER_AGENT_DEBUG_DIR=/path/to/dir`
  - 自定义 debug 根目录
- `COMPUTER_AGENT_DEBUG_SAVE_IMAGES=0`
  - 保留 JSON/TXT，不保存图片

## 常用配置

CLI 参数：

- `--api-key`
- `--base-url`
- `--model`
- `--user-agent`
- `--openai-timeout-seconds`
- `--max-steps-default`
- `--max-duration-s-default`
- `--debug-dir`
- `--log-level`
- `--kill-switch-file`

对应环境变量：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `COMPUTER_AGENT_OPENAI_API_KEY` | 无 | OpenAI 兼容接口的 API key。 |
| `OPENAI_API_KEY` | 无 | `COMPUTER_AGENT_OPENAI_API_KEY` 的兼容别名。 |
| `COMPUTER_AGENT_OPENAI_BASE_URL` | `https://api.openai.com/v1` | OpenAI 兼容接口的 base URL。 |
| `OPENAI_BASE_URL` | 无 | `COMPUTER_AGENT_OPENAI_BASE_URL` 的兼容别名。 |
| `COMPUTER_AGENT_OPENAI_MODEL` | `gpt-5.4` | 内部视觉 worker 使用的模型名。 |
| `COMPUTER_AGENT_OPENAI_USER_AGENT` | 无 | 向上游发送的自定义 `User-Agent`。 |
| `COMPUTER_AGENT_OPENAI_TIMEOUT_SECONDS` | `120` | 单次 OpenAI 请求超时秒数。 |
| `COMPUTER_AGENT_MAX_STEPS_DEFAULT` | `30` | 单次任务默认最大 step 数。 |
| `COMPUTER_AGENT_MAX_DURATION_S_DEFAULT` | `120` | 单次任务默认最长持续时间，单位秒。 |
| `COMPUTER_AGENT_MAX_TYPE_CHARS` | `200` | 单次 `type` 动作允许输入的最大字符数。 |
| `COMPUTER_AGENT_DEFAULT_PAUSE_MS` | `80` | 常规动作之间的默认暂停时间，单位毫秒。 |
| `COMPUTER_AGENT_POST_ACTION_WAIT_MS` | `500` | 动作执行后的附加等待时间，单位毫秒。 |
| `COMPUTER_AGENT_CONTROL_CURSOR` | `true` | 是否启用 Windows 本地“AI 正在控制”系统光标提示。 |
| `COMPUTER_AGENT_DEBUG_INCLUDE_CURSOR` | `true` | 是否只在 debug 截图里叠加鼠标准心辅助排查。 |
| `COMPUTER_AGENT_HUMAN_OVERRIDE` | `true` | 是否启用本地人工接管检测。 |
| `COMPUTER_AGENT_MOUSE_INTERRUPT_THRESHOLD_PX` | `15` | 判定鼠标手动介入时的移动阈值，单位像素。 |
| `COMPUTER_AGENT_KILL_SWITCH_FILE` | 无 | kill switch 文件路径；文件存在时任务会停止。 |
| `COMPUTER_AGENT_DEBUG` | `false` | 是否启用 run 级调试记录。 |
| `COMPUTER_AGENT_DEBUG_DIR` | `.computer_agent_mcp_debug/` | 调试输出根目录。 |
| `COMPUTER_AGENT_DEBUG_SAVE_IMAGES` | `true` | 是否保存 debug 截图。 |
| `COMPUTER_AGENT_LOG_LEVEL` | `INFO` | 服务端日志级别。 |

## 开发

```bash
pip install -e .[dev]
```

当前测试使用 `pytest`：

```bash
pytest
```

## 平台说明

当前只实现了 Windows 适配层。

如果在非 Windows 平台启动：

- server 可以启动
- 但实际桌面工具调用会因为平台不支持而失败

## 参考

- [REFERENCE.md](./REFERENCE.md)
