# computer-agent-mcp

一个面向通用 MCP host 的黑盒桌面任务 MCP。

当前实现的核心思路是：

1. 服务端捕获当前桌面截图
2. 服务端把任务、结构化近期执行轨迹、累计过程记忆和最新截图发给内部视觉模型
3. 模型基于当前截图返回观察、过程记忆增量、动作计划、期望结果，以及它看到的画面尺寸
4. 服务端按模型声明尺寸与真实截图尺寸做坐标换算
5. 服务端本地执行动作并继续循环
6. 对外只返回任务级结果，不把截图暴露给外部主 Agent

## 当前实现状态

截至当前版本，项目按下面这些前提运行：

- 仅支持 Windows
- 对外是无状态 task tool
- 每次调用都必须完整描述任务
- 服务端不提供 `resume` / `continuation_token`
- 新任务会抢占旧任务
- 内部默认使用 `Responses API + message + vision`，而不是原生 `computer` tool
- 单次 run 内会维护累计 memory，但不会跨调用持久化
- 模型需要返回它实际使用的 `image_width` / `image_height`
- 服务端据此做坐标缩放
- 允许模型在单轮返回多动作 batch

这意味着它不是“官方 computer use 的直接封装”，而是一个更偏工程化的黑盒视觉执行器。

## 为什么这样做

当前第三方 OpenAI-compatible 上游在原生 `computer` 路径上的兼容性并不稳定：

- 有的上游直接不支持
- 有的 `message` 和 `computer` 路径使用不同坐标系
- 有的 provider 会把图片内部归一化到更小画布

相比之下，普通图片消息路径通常更兼容。

因此本项目当前选择：

- 内部走更稳的 `message + vision`
- 外部保持任务级黑盒接口
- 由服务端自己处理截图、历史裁剪、坐标换算和动作执行

## 对外工具

### `computer_list_displays`

列出可用显示器。

适用场景：

- 多显示器环境
- 需要显式选择非主屏

大多数情况下可以直接使用默认 `display_id="primary"`。

### `computer_use_task`

运行一个无状态黑盒桌面任务。

输入：

- `task`
- `display_id`，默认 `primary`
- `max_steps`，可选

返回：

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
  - `step_index`
  - `observation`
  - `memory_update`
  - `summary`
  - `actions[]`
  - `expected_outcome`
  - `execution_status`
  - `execution_message`
  - `resulting_window_title`

字段语义：

- `summary`
  - 简短结果或本轮意图描述
- `result`
  - 更完整的最终交付内容
- `memory`
  - 单次 run 内累计得到的过程记忆
  - 例如已收集到的评论原文、候选项、标题、金额、页面要点
- `next_user_action`
  - 仅在 `blocked` 时使用，用于告诉人类下一步该做什么
- `trace`
  - 按时间线记录每一轮的：
    - 当前观察
    - 本轮新增记忆
    - 本轮意图
    - 动作
    - 期望结果
    - 执行结果

注意：

- 这是无状态接口
- 每次调用都会从“当前桌面”重新开始
- 服务端不会跨调用保留截图、history 或 memory
- 如果上一次被打断，外部需要根据当前画面重新完整描述任务
- 如果结果是 `block_reason=human_override`，不要直接自动重试；应先询问用户为什么介入、当前画面是否仍可继续，再决定是否重新调用
- tool result 同时包含：
  - `structuredContent`
    - 完整 JSON 结果
  - `content`
    - 人类可读摘要，包含 `result`、累计 `memory` 和完整时间线 trace

### 运行中 progress

长任务执行期间，服务端会持续发送 MCP `notifications/progress`。

典型消息包括：

- `Capturing current screen`
- `Requesting vision worker for step 1`
- `Still waiting for vision worker for step 1`
- `Step 1 action 1/2: wait 1500ms`
- `Step 1 action 1/2: waiting 1500ms (500/1500ms)`
- `Capturing updated screen after step 1`
- `Finished`

## 运行语义

### 无状态

服务端不维护跨调用任务上下文。

所以：

- 不要假设有 resume
- 不要假设会记住旧截图
- 不要假设会跨调用记住旧 memory
- 每次调用都必须给完整任务目标

但在单次 run 内，服务端会维护两类内部状态：

- `history`
  - 近期执行轨迹，告诉模型前几步做了什么
- `memory`
  - 本轮任务过程中累计得到的任务相关信息
  - 每轮模型只返回新增的 `memory_update`
  - 服务端负责追加并在下一轮继续带回模型

### 新任务抢占旧任务

桌面控制本质上是单活动任务模型。

当前实现里：

- 同时只允许一个活动任务
- 如果新任务进来，会向旧任务发送取消信号
- 旧任务会以 `superseded` 结束
- 新任务接管执行

### 批量动作

模型单轮可以返回多个动作：

- 服务端按顺序执行
- 一旦其中某个动作失败/超时/被人工打断，后续动作不再执行
- 执行完当前批次后再重新截图进入下一轮

当任务目标依赖中间画面的信息读取、收集、比较或验证时，提示词会明确要求模型优先采用更小的动作批次，避免一次跳过多个可能有信息价值的中间状态。

### 人工优先

如果本地用户真实介入键盘或鼠标：

- 当前执行会停止
- 任务返回 `blocked`
- `block_reason` 为 `human_override`
- 外部调用方不应无条件自动重试，而应先向用户确认介入原因，以及是否希望从当前画面继续

## 坐标与图片策略

当前实现不主动缩小截图后再发给模型。

取而代之的是：

- 发送当前截图原图
- 发给模型的是原始截图，不额外叠加鼠标准心；debug 保存的截图可单独叠加准心辅助排查
- Windows 默认会在单次 run 期间临时切换系统鼠标样式，用来提示“AI 正在控制”；run 结束后会自动恢复当前用户的光标方案
- 这套 Windows 控制光标资源默认放在 `computer_agent_mcp/assets/cursor/`，以语义英文文件名组织，例如 `normal_select.ani`、`text_select.ani`、`wait.ani`
- 如需关闭这项本地提示，可设置 `COMPUTER_AGENT_CONTROL_CURSOR=false`
- 如果控制光标初始化、资源加载或恢复失败，任务本身不会因此中断；服务端会降级继续执行，并把原因写入 `warnings`
- 要求模型显式返回：
  - `image_width`
  - `image_height`
  - 以及基于该尺寸的动作坐标
- 服务端根据：
  - 模型声明尺寸
  - 真实截图尺寸
  做等比换算

这样做的原因是：不同上游对视觉输入的内部工作画布并不一致，盲信 `detail=original` 不够可靠。

## 内部动作集合

当前内部动作语义包括：

- `move`
- `click`
- `double_click`
- `right_click`
- `drag`
- `scroll`
- `type`
- `keypress`
- `wait`

其中：

- `scroll` 使用语义化方向
  - `direction="down"` 表示页面向后滚动到更靠后的内容
  - `direction="up"` 表示页面回到更靠前的内容
- 任何会触发鼠标定位的动作（如 `click` / `drag` / `scroll`）都会先以可见轨迹将指针移动到目标位置，再执行对应动作
- 上面的“AI 控制中”鼠标指示只作用于本地用户界面提示，不会叠加进发给模型的截图
- `type` 会受最大字符数限制
- `wait` / `type` / 鼠标动作执行过程中都会检查：
  - 人工接管
  - 新任务抢占
  - kill switch
  - 总任务 deadline

## 阻塞与失败

服务端不会主动做一套“官方式风险确认拦截”。

当前阻塞/失败更多来自：

- 模型自己返回 `blocked`
- 人工接管
- 超时
- kill switch
- 执行器错误
- 新任务抢占

常见 `block_reason` 可能包括：

- `human_override`
- `timeout`
- `superseded`
- `environment_error`
- `ambiguous`
- 以及模型自己返回的阻塞原因

## 调试模式

支持完整 run 级调试记录。

默认目录：

- `.computer_agent_mcp_debug/<run_id>/`

每一轮任务会生成独立 run 目录，里面通常包括：

- `events.jsonl`
  - 全量事件时间线
  - 现在也会记录 progress 序列
- `task.txt`
  - 原始任务描述
- `run_config.json`
  - 本轮运行配置摘要
- `result.json`
  - 最终任务结果，包含 `result`、累计 `memory` 和 trace
- `step_XX_request.json`
  - 发给模型的该轮完整请求摘要
  - 图片 base64 会被占位符替代
  - 包含最近 history 和当前累计 memory
- `step_XX_response.json`
  - 该轮模型响应摘要
  - 包含解析后的 decision、usage 和 raw response
- `images/`
  - 原始截图
  - 动作覆盖图

这套输出就是你调试定位错误、模型决策错误、执行器映射错误时的主要依据。

相关环境变量：

- `COMPUTER_AGENT_DEBUG=0`
  - 关闭 debug 记录
- `COMPUTER_AGENT_DEBUG_DIR=/path/to/dir`
  - 自定义 debug 根目录
- `COMPUTER_AGENT_DEBUG_SAVE_IMAGES=0`
  - 保留 JSON/TXT，不保存图片

## 安装

```bash
pip install -e .
```

如果你使用自己的虚拟环境，确保至少安装：

- `openai`
- `mcp[cli]`
- `pydantic`
- `mss`
- `Pillow`
- `pynput`

## 运行

当前入口为 stdio MCP server。

```bash
python -m computer_agent_mcp \
  --api-key sk-... \
  --base-url https://api.openai.com/v1 \
  --model gpt-5.4 \
  --user-agent "Codex Desktop/0.115.0-alpha.4"
```

也可以通过环境变量提供 key：

- `COMPUTER_AGENT_OPENAI_API_KEY`
- `OPENAI_API_KEY`

如果需要给上游显式发送 `User-Agent`，可以二选一：

- 启动参数：`--user-agent`
- 环境变量：`COMPUTER_AGENT_OPENAI_USER_AGENT`

默认不发送自定义 `User-Agent`。

## 常用配置

- `--api-key`
- `--base-url`
- `--model`
- `--user-agent`
- `--openai-timeout-seconds`
- `--max-steps-default`
- `--max-duration-s-default`
- `--debug-dir`
- `--kill-switch-file`

对应环境变量：

- `COMPUTER_AGENT_OPENAI_API_KEY`
- `COMPUTER_AGENT_OPENAI_BASE_URL`
- `COMPUTER_AGENT_OPENAI_MODEL`
- `COMPUTER_AGENT_OPENAI_USER_AGENT`
- `COMPUTER_AGENT_OPENAI_TIMEOUT_SECONDS`
- `COMPUTER_AGENT_MAX_STEPS_DEFAULT`
- `COMPUTER_AGENT_MAX_DURATION_S_DEFAULT`
- `COMPUTER_AGENT_MAX_TYPE_CHARS`
- `COMPUTER_AGENT_DEFAULT_PAUSE_MS`
- `COMPUTER_AGENT_POST_ACTION_WAIT_MS`
- `COMPUTER_AGENT_DEBUG_INCLUDE_CURSOR`
- `COMPUTER_AGENT_HUMAN_OVERRIDE`
- `COMPUTER_AGENT_MOUSE_INTERRUPT_THRESHOLD_PX`
- `COMPUTER_AGENT_KILL_SWITCH_FILE`

## 平台说明

当前只实现了 Windows 适配层。

如果在非 Windows 平台启动：

- server 可以启动
- 但实际桌面工具调用会因为平台不支持而失败

## 参考

- [REFERENCE.md](./REFERENCE.md)
