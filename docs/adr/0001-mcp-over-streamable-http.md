# ADR-0001 MCP over Streamable HTTP，单工具 + 诊断工具

- 状态：已接受
- 日期：2026-11-16

## 背景

上游 WeVisOne-VL 已经在 Windows 主机上跑通（2B，GPU 主干 + CPU 解码器）。
目标是让 DeepSeek Harness 之类的 MCP 客户端跨机器调用这份视觉能力。

可选接入形态：

1. DSH 原生插件（TypeScript）
2. MCP server（Python）
3. 直接 HTTP API

## 决策

先做 **MCP server**，传输用 **Streamable HTTP**，只暴露两个工具：

- `wevisone_predict(image_base64, task, query)`
- `wevisone_doctor()`

不拆成 7 个细分工具，不做鉴权体系（仅一个可选共享令牌），不做批量与队列。

## 后果

正面：

- 不碰 DSH 源码，任何 MCP 客户端都能接；本会话已有 MCP 消费先例（`mcp__penpot__*`）。
- 上游 `predict()` 本身已覆盖全部 11 个 task，一个工具即可表达，schema 里的枚举自带说明。
- 跨机天然成立：模型留在 GPU 所在的 Windows，Mac 只发请求。

代价：

- 工具入参必须是 base64（不接受服务器路径），大图受请求体上限约束（当前 32 MiB）。
- 像素结果以 base64 PNG 返回，单张 alpha 约 30 KB 文本；多目标时响应会变大。
- 6GB 显存下推理串行，`_infer_lock` 保证不并发爆显存。

## 被否方案

- **DSH 原生插件**：能做图卡片与生命周期管理，但工作量大得多，且首版不需要 UI。
- **细分 7 个工具**：与"最小实现"冲突；工具选择质量目前无证据说明需要拆分。
- **stdio 传输**：模型在另一台机器上，stdio 需要隧道转发，不如 HTTP 直接。
- **SSE（旧传输）**：Streamable HTTP 是当前规范方向，客户端支持更好。

## 后续动作

- 需要图卡片或编辑器式交互时，再评估原生插件（路线 A）。
- 多客户端并发需求出现时，换 24GB 显卡并去掉串行锁。
