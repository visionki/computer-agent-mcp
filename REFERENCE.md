# computer-agent-mcp reference

## 文档目的

这份文档不承担项目介绍职责，只记录当前阶段与开发决策直接相关的事实、实验结论和外部参考。

它服务于后续开发者，帮助回答下面几个问题：

- 为什么 `computer-agent-mcp` 当前要优先做成黑盒任务型 MCP
- 为什么首版默认绑定 `gpt-5.4`
- 为什么不把截图直接返给外部主 Agent
- 为什么动作语义要尽量贴近官方 `computer use`

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

- v1 不能假设“小模型也差不多”
- 模型适配层必须作为显式抽象存在

## 与交互型项目的边界

`computer-agent-mcp` 和 `computer-vision-mcp` 不是“同一套协议的两个模式”，而是两个独立项目。

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

## 本地实验结论摘要

以下结论来自当前工作区已完成的坐标调查，适合作为设计约束，而不是营销表述。

### 1. 问题不只是“模型点偏了”

在不同上游和不同请求路径下，同一目标可能被返回在不同坐标系里。

典型现象：

- 某些请求路径返回接近 `1920x1080` 原图坐标
- 某些请求路径稳定落在 `1366x768` 一类缩小工作画布坐标

因此很多所谓“定位不准”，本质上是工作画布变了，而不是目标找错了。

### 2. `message` 与原生 `computer` 路径不一定暴露同一画布

这意味着：

- 不能把第三方上游的原生 `computer` 当作稳定基线
- 如果未来要兼容多个 provider，必须允许不同视觉 worker adapter

### 3. `detail=original` 不是可靠的协议承诺

不能把“传了 original”理解成“坐标一定回到原图空间”。

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

## 外部同类项目参考

### 1. OpenAI CUA sample app

价值：

- 官方提供的最近参考实现
- 同时展示 `native` computer mode 和 `code` mode
- 说明 OpenAI 自己也没有把“纯坐标点击”当成唯一落地方式

启发：

- 黑盒项目应优先重视运行循环和回放，而不是只重视工具面

### 2. domdomegg/computer-use-mcp

价值：

- 典型的“主模型看图、MCP 只执行”的原始视觉 MCP

启发：

- 这类项目已经存在
- `computer-agent-mcp` 不应该重复做一个“把截图返给主 Agent”的变体

### 3. Windows-MCP / QuickDesk / computer-control-mcp

价值：

- 提供了执行层、系统集成层、远程控制层的现成参照

启发：

- 黑盒项目真正的差异点不在键鼠注入，而在服务端内部视觉 worker loop

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
