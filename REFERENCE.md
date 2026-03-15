# computer-agent-mcp reference

## 文档目的

这份文档不承担项目介绍职责，只记录当前阶段与开发决策直接相关的事实、实验结论、外部参考，以及详细的运行语义。

它服务于后续开发者，帮助回答下面几个问题：

- 为什么 `computer-agent-mcp` 当前要优先做成黑盒任务型 MCP
- 为什么首版默认绑定 `gpt-5.4`
- 为什么不把截图直接返给外部主 Agent
- 为什么动作语义要尽量贴近官方 `computer use`

---

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

## 为什么这样做

这个项目没有直接把"主 Agent 看图 + MCP 只执行动作"作为默认路线，主要是因为现实兼容性问题：

- 不同 host 对图片桥接和图片结果消费能力并不稳定
- 不同 provider 的原生 `computer` 或视觉路径坐标系不一定一致
- 多轮截图直接堆进主上下文，体积和控制复杂度都很高

因此当前实现选择：

- 内部使用 `Responses API + message + vision`
- 对外保持任务级黑盒接口
- 由服务端自己负责截图、坐标换算、动作执行、短期轨迹和调试记录

---

## 运行语义

### 无状态

这是一个无状态接口：

- 每次调用都会从"当前桌面"重新开始
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

---

## 对外工具详细说明

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

### `computer_list_displays`

列出可用显示器。

适合：

- 多显示器环境
- 需要显式选择非主屏

大多数情况下直接使用默认 `display_id="primary"` 即可。

---

## 坐标、截图与本地控制

当前实现不主动缩小截图后再发给模型，而是：

- 发送当前截图原图
- 要求模型显式返回 `image_width` 和 `image_height`
- 服务端根据模型声明尺寸和真实截图尺寸做等比换算

另外还有几条运行约束：

- 发给模型的是原始截图，不额外叠加鼠标准心
- debug 保存的截图可以单独叠加准心辅助排查
- Windows 默认会在单次 run 期间临时切换系统鼠标样式，用来提示"AI 正在控制"
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

---

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

---

## 完整配置参考

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
| `COMPUTER_AGENT_CONTROL_CURSOR` | `true` | 是否启用 Windows 本地"AI 正在控制"系统光标提示。 |
| `COMPUTER_AGENT_DEBUG_INCLUDE_CURSOR` | `true` | 是否只在 debug 截图里叠加鼠标准心辅助排查。 |
| `COMPUTER_AGENT_HUMAN_OVERRIDE` | `true` | 是否启用本地人工接管检测。 |
| `COMPUTER_AGENT_MOUSE_INTERRUPT_THRESHOLD_PX` | `15` | 判定鼠标手动介入时的移动阈值，单位像素。 |
| `COMPUTER_AGENT_KILL_SWITCH_FILE` | 无 | kill switch 文件路径；文件存在时任务会停止。 |
| `COMPUTER_AGENT_DEBUG` | `false` | 是否启用 run 级调试记录。 |
| `COMPUTER_AGENT_DEBUG_DIR` | `.computer_agent_mcp_debug/` | 调试输出根目录。 |
| `COMPUTER_AGENT_DEBUG_SAVE_IMAGES` | `true` | 是否保存 debug 截图。 |
| `COMPUTER_AGENT_LOG_LEVEL` | `INFO` | 服务端日志级别。 |

---

## 当前阶段判断

截至 2026-03-14，黑盒任务型视觉 MCP 是当前最可落地的路线。

原因不是它最理想，而是它最适合当前 MCP 客户端现实：

- 通用 host 对图片工具结果的桥接并不可靠
- 多轮截图会迅速推高主 Agent 上下文体积
- 即使模型具备视觉能力，外部主 Agent 也未必适合作为图片持有者

因此，黑盒 MCP 的核心价值是把以下内容全部收回服务端：

- 截图
- 图像输入
- 坐标空间
- 动作执行
- 历史裁剪
- 任务恢复

## 当前模型判断

当前首版默认基于 `gpt-5.4`，理由是：

- 已有本地实验表明它在截图定位和返回点击坐标方面明显优于更早模型代际
- OpenAI 官方当前明确把 `gpt-5.4` 和 `gpt-5.4-pro` 列为支持 `computer use` 的模型
- 当前未把 `gpt-5 mini`、`gpt-5 nano` 作为 `computer use` 支持模型

这不意味着未来只支持 `gpt-5.4`，但意味着：

- v1 不能假设"小模型也差不多"
- 模型适配层必须作为显式抽象存在

## 与交互型项目的边界

`computer-agent-mcp` 和 `computer-vision-mcp` 不是"同一套协议的两个模式"，而是两个独立项目。

黑盒项目负责：

- 面向通用 host 的任务委托
- 服务端内部视觉循环
- `blocked / resume / continuation_token`

交互项目负责：

- 面向外部主 Agent 的截图和动作协议
- `state_id`
- 坐标空间协商
- host 图片桥接验证

不要把交互协议强塞进黑盒项目的 v1。

---

## 本地实验结论摘要

以下结论来自当前工作区已完成的坐标调查，适合作为设计约束，而不是营销表述。

### 1. 问题不只是"模型点偏了"

在不同上游和不同请求路径下，同一目标可能被返回在不同坐标系里。

典型现象：

- 某些请求路径返回接近 `1920x1080` 原图坐标
- 某些请求路径稳定落在 `1366x768` 一类缩小工作画布坐标

因此很多所谓"定位不准"，本质上是工作画布变了，而不是目标找错了。

### 2. `message` 与原生 `computer` 路径不一定暴露同一画布

这意味着：

- 不能把第三方上游的原生 `computer` 当作稳定基线
- 如果未来要兼容多个 provider，必须允许不同视觉 worker adapter

### 3. `detail=original` 不是可靠的协议承诺

不能把"传了 original"理解成"坐标一定回到原图空间"。

服务端必须自己定义并控制：

- 截图尺寸
- 图片输入策略
- 坐标换算逻辑

### 4. 历史截图不能无限累积

图片一旦持续累积到主上下文或 worker 输入中，很快就会形成请求体膨胀问题。

因此黑盒项目需要明确采用：

- 最近一张截图
- 极短文本轨迹
- 旧截图直接丢弃

---

## 外部同类项目参考

### 1. OpenAI CUA sample app

价值：

- 官方提供的最近参考实现
- 同时展示 `native` computer mode 和 `code` mode
- 说明 OpenAI 自己也没有把"纯坐标点击"当成唯一落地方式

启发：

- 黑盒项目应优先重视运行循环和回放，而不是只重视工具面

### 2. domdomegg/computer-use-mcp

价值：

- 典型的"主模型看图、MCP 只执行"的原始视觉 MCP

启发：

- 这类项目已经存在
- `computer-agent-mcp` 不应该重复做一个"把截图返给主 Agent"的变体

### 3. Windows-MCP / QuickDesk / computer-control-mcp

价值：

- 提供了执行层、系统集成层、远程控制层的现成参照

启发：

- 黑盒项目真正的差异点不在键鼠注入，而在服务端内部视觉 worker loop

---

## 对 v1 的直接约束

### 必做

- 任务级工具
- continuation token
- 人工接管中断
- 短轨迹
- 动作日志
- 每轮截图调试记录

### 不急着做

- 多 provider 自动切换
- 多模型评分路由
- 云沙箱和远程桌面
- 外部可见的逐步动作流

## 推荐的首轮开发顺序

1. 固定项目目录骨架
2. 建立平台适配层
3. 定义内部动作协议
4. 定义任务级 MCP tools
5. 接入 `gpt-5.4` worker adapter
6. 跑通最小循环
7. 补 `blocked / resume`
8. 补回放和调试

## 参考链接

- OpenAI computer use guide:
  [https://developers.openai.com/api/docs/guides/tools-computer-use/](https://developers.openai.com/api/docs/guides/tools-computer-use/)
- OpenAI GPT-5.4 announcement:
  [https://openai.com/nb-NO/index/introducing-gpt-5-4/](https://openai.com/nb-NO/index/introducing-gpt-5-4/)
- OpenAI sample app:
  [https://github.com/openai/openai-cua-sample-app](https://github.com/openai/openai-cua-sample-app)
- domdomegg/computer-use-mcp:
  [https://github.com/domdomegg/computer-use-mcp](https://github.com/domdomegg/computer-use-mcp)
- Local coordinate investigation:
  [COORDINATE_INVESTIGATION.md](E:/project/playground/computer-use/projects/openai-native-computer-use/COORDINATE_INVESTIGATION.md)
