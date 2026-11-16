# AGENTS.md · WeVisOne-VL-MCP

> 仓库级开发契约，面向 AI 编码代理与人类协作者。
> 版本 v0.1 | 2026-11-16 | 适用范围：整个仓库
>
> 读法：每次会话先读 §0–§2；接任务读 `docs/ROADMAP.md`；写代码按 §3–§4；交付前过 §5。**进度只记录在 ROADMAP。**

## 0. 60 秒进入状态

**一句话**：把 Tencent WeVisOne-VL 的视觉感知能力（检测/指代/计数/指向/OCR/分割/抠图）
封装成标准 MCP server，让任何 MCP 客户端（DeepSeek Harness 等）通过 HTTP 直接调用。

**当前状态**（详见 `docs/ROADMAP.md`）
- **已进入生产实测**：MCP server + DSH 插件 v0.6.2 在真实任务中迭代；`wevisone-vision` skill **已冻结**
- 上游 WeVisOne-VL **不改动**：本仓库只做封装层
- 运行位置：代码在 Mac 编写，server 跑在 Windows 主机 `dell-16-plus`（GPU），插件跑在用户 Windows PC
- 接手生产问题直接读 **§7**

**先记住这几条**
1. 上游 `WeVisOne-VL` 是只读依赖，任何时候都不修改它。
2. 一次只做一个 ROADMAP 任务；做完必须验证、回写状态、报告证据。
3. 模型实例**必须常驻**：单次加载约 10 秒，禁止每次调用重新加载。
4. 工具返回值只放 JSON + 文本；MCP 结果里不放图片（宿主会拒绝 ImageBlock）。
5. 最小实现优先：先走必要性阶梯，写前列反向清单。

### 0.1 文档优先级（冲突裁决）

| 优先级 | 文件 | 管什么 | 冲突时谁赢 |
|---:|---|---|---|
| 1 | `AGENTS.md` §2 | 业务铁律 | 铁律 |
| 2 | `docs/adr/` | 技术决策 | 技术实现 |
| 3 | `docs/ROADMAP.md` | 进度与待决 | 状态 |
| 4 | 现有代码 | 现状 | 偏离基线时改代码 |

### 0.2 遇到冲突怎么办

不静默选；登记到 ROADMAP §5 待决问题；用一个最小问题问用户（给默认方案）；确认后先改文档再写代码。

## 1. 产品范围与固定术语

### 1.1 用户与场景

- 用户：需要让 AI 代理具备精确视觉定位能力的开发者（先服务于本机 DeepSeek Harness）。
- 场景：代理在对话中需要「物体在哪（框/点）」「计数」「抠图（alpha）」「文字在哪」。

### 1.2 MVP 边界

**做**：MCP over HTTP 的工具面、模型常驻、跨机调用、健康诊断。
**不做**：训练/微调、批量队列、鉴权体系（首版局域网内网使用，第一版只做可选共享令牌）、
原生 DSH 插件形态、Web UI、Gradio 复刻。

### 1.3 固定术语与枚举

| 术语 | 含义 |
|---|---|
| `task` | 上游能力名，枚举见 `wevisone_mcp/shaping.py: TASKS` |
| `box` | 归一化 `[x1,y1,x2,y2]`，取自上游输出，范围 0–1 |
| `point` | 归一化 `[x,y]`，范围 0–1 |
| `alpha` | 连续透明度 matte，0–1 浮点 |
| `rejected` | 上游判定目标不存在（输出 `none`） |

`task` 枚举的权威来源是上游 `prompts.py` 的 `TASKS`；本仓库在 `shaping.py` 保留一份
**镜像**，由 `tests/test_shaping.py::test_tasks_match_upstream` 守卫漂移（上游不可导入时跳过）。
允许镜像的理由：`wevisone_vl` 的包 `__init__` 会拉重依赖，shaping 必须能在无 GPU 机器上单独测试。

## 2. 业务铁律（不可违背）

| ID | 铁律 | 依据 | 验证方式 |
|---|---|---|---|
| I-01 | 上游 `WeVisOne-VL` 仓库只读，本仓库不改其任何文件 | 用户指令 2026-11-16 | `git -C <upstream> status --porcelain` 为空 |
| I-02 | 模型实例在一次进程生命周期内只加载一次 | 冷启动 ~10s，重复加载不可接受 | `TestSingleton_LoadsOnce` |
| I-03 | MCP 工具结果不得包含图片块，只返回 JSON 与文本 | 宿主拒绝 ImageBlock | `TestShaping_*` 返回值均为可 JSON 序列化对象 |
| I-04 | 目标不存在时如实返回 `rejected=true`，不编造坐标 | 上游拒绝能力是核心价值 | `TestShaping_Rejected` |
| I-05 | 图像只能以 base64 或**服务端签发的 upload_id** 提供，永不接受客户端给出的文件路径 | 跨机使用 + 避免路径穿越 | `TestResolveRejects` 全部通过；工具 schema 无 path 字段 |
| I-06 | 模型在进程启动时预加载，冷加载不得落在工具调用内 | 冷加载约 7s，会掐断客户端 SSE 流 | 重启后首调 `wevisone_doctor` 返回 `model_loaded=true` |
| I-07 | 绑定非回环地址时必须配置共享令牌，且令牌只能来自环境变量或 0600 文件 | 局域网暴露无人值守的 GPU 服务；字面量落在配置/任务参数里等于公开 | `main()` 在无令牌时退出码 2；`serve.ps1` 任务参数只含路径；`cordis.patch.yml` 无字面量 |
| I-08 | `upload_id` 只由服务端生成且必须是 32 位小写 hex；不匹配即拒绝 | 让 id 无法携带路径语法 | `TestUploadId` + `TestResolveRejects` |

## 3. 仓库结构与分层

### 3.1 目录树

```
WeVisOne-VL-MCP/
├─ AGENTS.md                 本契约
├─ README.md                 安装与运行
├─ docs/ROADMAP.md           唯一进度源
├─ docs/adr/                 技术决策
├─ wevisone_mcp/
│  ├─ shaping.py             纯函数：入参校验 + 上游结果整形（无 torch）
│  ├─ uploads.py             upload_id 签发/解析/过期清理（仅标准库）
│  ├─ client.py              进程内 Python API（PIL 掩版，不走 HTTP）
│  ├─ cli.py                 命令行客户端（仅标准库，走 REST）
│  └─ server.py              MCP 工具面 + 模型单例 + /upload + /predict + /artifacts
├─ plugin/                   DSH 插件开发环境（Docker）；子模块仓库地址见 README
├─ plugin/dsh-wevisone-mcp-plugin/  ← git submodule: PeiJingbobo/dsh-wevisone-mcp-plugin
├─ scripts/service.sh        Linux systemd 注册/注销/状态
├─ docs/mcp-server.md        MCP 服务器部署/接入文档（面向所有 agent）
├─ docs/dsh-plugin.md        DSH 原生插件文档（只面向 DSH）
├─ tests/                    单元测试
├─ scripts/                  部署与探测脚本
└─ client_check.py           端到端 MCP 客户端自检
```

### 3.2 分层规则

- `shaping.py` **不得** import torch / mcp / PIL 以外的重依赖，保证 Mac 上可无 GPU 跑测试。
- `server.py` 唯一允许接触模型与 MCP SDK 的地方；`client.py` 只允许复用 `server` 与 `shaping`，不新增推理路径。
- 依赖方向：`client.py` / `server.py` → `shaping.py` + `uploads.py`；后两者不反向依赖。
- 上游能力调用只有一处：`server.get_engine()`。
- 同一张 GPU 上 `client.py` 与 MCP 服务**不得并行运行**（两份 2B 主干超出 6 GB）。

### 3.3 新代码放哪

| 改动类型 | 位置 |
|---|---|
| 结果整形 / 入参校验 | `wevisone_mcp/shaping.py` |
| 新工具 / 模型调用 | `wevisone_mcp/server.py` |
| 纯逻辑测试 | `tests/` |
| 部署、探测 | `scripts/` |

### 3.4 命名规范

Python `snake_case`；MCP 工具名统一 `wevisone_` 前缀；环境变量统一 `WEVISONE_MCP_` 前缀。

## 4. 工程约定

### 4.1 技术栈与命令契约

- Python 3.12（Windows 侧复用 `AITools\venv-wevisone`）
- 依赖：`mcp`（2.x，`MCPServer`）、上游 `wevisone_vl`、`Pillow`

| 用途 | 命令 |
|---|---|
| 单测（Mac，无需 GPU） | `python3 -m unittest discover -s tests -v` |
| 起服务（Windows 前台） | `<venv>\Scripts\python.exe -u -m wevisone_mcp.server` |
| 起服务（Windows 常驻） | `powershell -File scripts\serve.ps1 -BindHost 0.0.0.0 -Token <secret>` |
| 端到端自检 | `python client_check.py --url http://127.0.0.1:8000/mcp` |

> 以上命令均已实测通过（ROADMAP §3 AC-01..AC-06）。未实测的命令不得写入本表。

### 4.2 服务端规范

- 绑定地址、端口、令牌全部走环境变量，带可用默认值。
- 默认绑定 `127.0.0.1`；对外开放必须显式设置 host 并配置令牌。
- 单进程单模型；并发由 HTTP 层排队，不做自定义队列。

### 4.3 API 契约

- 传输：MCP Streamable HTTP，路径 `/mcp`。
- 工具返回：一个 JSON 对象序列化后的文本；字段稳定、可判空。
- 图像输入：`POST /upload`（原始字节，需令牌）→ `upload_id`；工具用 `upload_id` 或内联 `image_base64` 引用。
- 像素产物：落盘后只在响应里给相对 URL `{"index","url","bytes","content_type"}`，用 `GET /artifacts/<id>` 下载（需令牌，可过期）。**响应永不内联图像字节。**
- REST 逃生门：`POST /predict`（JSON 入参同工具，返回同样的 JSON）供插件与非 MCP 客户端使用；与工具共用 `run_predict()`，不得各写一套。
- `boxes` 必须有值：引擎结果优先，为空且无掩码时由 `shaping.parse_boxes()` 从 `response` 回退解析（上游 `parse_seg_boxes` 只认 `<OBJ>`，会把纯检测回答的框丢掉）；像素任务不回退，保持与 `artifacts` 对齐。
- 两种角色：本地模式加载模型；设置 `WEVISONE_REMOTE_URL` 后进入远端模式，`/mcp` `/predict` `/upload` `/artifacts` 全部转发且**不得**导入 torch。
- **`wevisone-vision` skill 已冻结（2026-11-17，v0.6.2，9,168 字节）。** 只在出现**新类型失败**时
  才允许加规则。判定标准（三条全中才算新类型）：
  1. 已有规则**改个措辞就能防住**的，属于变体，不许加新规则；
  2. 能给出一次真实会话证据，说明模型**按现有规则做了却仍然失败**；
  3. 新增净体积 ≤ 300 字节（超了先删等量的重复表述，净增为零）。
  同族的「多跑一次 / 多存一份 / 多看一眼」都算变体，不再累积规则。
- **插件每次改动必须升版本号**（`plugin/dsh-wevisone-mcp-plugin/package.json`）并在 CHANGELOG 记一行；运行时版本由 `wevisone_doctor` 的 `version` 暴露，`test/save-dir.mjs` 断言两者一致。别人只靠这个判断是否真的装了新版。
- 文档分工：`docs/mcp-server.md` 面向所有 MCP/REST 使用者，`docs/dsh-plugin.md` 只写 DSH 插件；README 只做索引，不重复细节。
- 错误：以 `{"ok": false, "error": "..."}` 返回，不抛裸异常给客户端。

### 4.9 项目技能

遵循 `engineering-contract`（项目契约 / 每轮一任务 / 最小实现 / 证据交付）。

### 4.10 最小实现与复杂度纪律

- 走必要性阶梯，停在第一个能过验收的选项。
- 写代码前列反向清单；拒绝对单一调用点抽 helper。

## 5. 开发循环

一轮只做一个任务：

```
进入 → 领任务 → 声明模式 → 六行计划 → 实现 → 验证 → 回写 → 汇报
```

### 5.1 六行计划模板

```text
目标 / 改动文件 / 数据接口影响 / 必要性阶梯+反向清单 / 测试计划 / 风险
```

### 5.2 验证阶梯

```
unittest（Mac 纯逻辑） → 真机 MCP 客户端自检 → 客户端工具清单核对
```

### 5.3 汇报模板

```text
✅ 完成 / 🧪 验证 / ⚠️ 偏差风险 / 🧹 克制 / ➡️ 下一步
```

## 6. 危险区（禁止事项）

1. ❌ 修改上游 `WeVisOne-VL` 仓库任何文件。
2. ❌ 在工具返回值里塞图片块。
3. ❌ 每次调用重新加载模型。
4. ❌ 把「没跑过」说成「已验证」。
5. ❌ 无令牌把服务绑定到 `0.0.0.0`。
6. ❌ 一轮领多个任务。

## 7. 生产运行与实测迭代

**给「没有上文的新会话」看的**：这一段自成闭环，照它就能接手一次生产问题。

### 7.1 部署矩阵（三处，别搞混）

| 角色 | 机器 | 位置 | 版本怎么查 |
|---|---|---|---|
| 模型服务 | `dell-16-plus`（RTX 3060 Laptop 6GB，LAN `192.168.1.12:8000`） | `C:\Users\PeiJingbo\MyCode\WeVisOne-VL-MCP`；计划任务 `WeVisOneMCP`，**开机自启**（SYSTEM） | 无版本号，跟仓库走 |
| DSH 插件 | **用户 Windows PC**（DSH 所在） | `~/.dsh/profiles/desktop/node_modules/dsh-wevisone-mcp-plugin` | `wevisone_doctor` 的 `version` |
| 发版源 | GitHub | `PeiJingbobo/WeVisOne-VL-MCP` + submodule `dsh-wevisone-mcp-plugin` | `package.json` |

⚠️ **附件与产物在用户 PC，不在 GPU 机。** 去 `dell-16-plus` 找 `Downloads\P5.webp` 会找不到。

### 7.2 每轮实测的固定动作

```
开始时：wevisone_doctor({"reset": true})     # 记基线并清零
结束时：wevisone_doctor()                    # 读本轮 predict_calls / total_latency_s
```

`version` 对不上 = 没装上、或装了没重启 DSH（配置和插件都在启动时读）。

### 7.3 复盘必须有三样证据，缺一不可

| # | 证据 | 用途 |
|---|---|---|
| 1 | `session.v4.jsonl` 路径 | 数调用次数、看有没有 `read_image` |
| 2 | `wevisone_doctor` 返回 | 版本 + 本轮耗时/失败/拒绝计数 |
| 3 | **产出文件原件（不要截图）** | 质量只能用像素判断，截图会失真 |

缺第 3 样就只能猜；猜出来的「修好了」不算验证。

### 7.4 归因顺序（不许跳级）

1. **服务端 bug** —— 能用像素或数值证伪的（例：alpha 截断成 254）。优先级最高。
2. **插件 bug** —— 参数没生效、路径错、返回结构不符（例：`save_dir` 只声明不实现）。
3. **skill 规则** —— 只有**新类型失败**且满足 §4.3 的三条判定才动；变体一律改措辞。

### 7.5 已知边界（是特性，不是 bug）

| 现象 | 原因 | 应对 |
|---|---|---|
| 并发任务变慢 | 6 GB VRAM，`_infer_lock` 串行推理 | 排队，别并发压 |
| 大图细节丢失 | 服务端先缩到自己的像素预算 | 框是归一化的，位置仍准；细线会丢 |
| `matting` 十几秒 | 每个 `<OBJ>` 解一张掩码，耗时随框数线性增长 | 单目标用 `segmentation` |
| 跨两次调用拼不出完整主体 | `compose` 只作用于**单次**调用 | 多调用时自己 union 掩码，别请求 `compose` |
| 主体右边被硬边切断 | 原图里就被画幅截断（`touches_edge: true`） | 抠图补不出来，只能生成式补全 |
| 远程/异网不可达 | 服务只绑 LAN | 用 `WEVISONE_REMOTE_URL` 代理或 VPN |

### 7.6 质量判据（不读图）

看 `stats`，不看 PNG：

- `verdict != "ok"` → 不交付，报 `problems`
- `coverage` 0.01–0.9、`alpha_max ≥ 0.9`、`touches_edge` 应为 `false`
- **抠图内部必须是 alpha 255**。出现 254 就是编码 bug（2026-11-17 修过：`astype(uint8)` 截断，
  导致所有抠图内部只有 99.6% 不透明，换背景发灰）。回归检查：
  `np.asarray(Image.open(p).getchannel('A')).max() == 255`

### 7.7 一次改动的完整发版动作

**插件**：升 `package.json` 版本 → CHANGELOG 记一行 → `node test/save-dir.mjs` 全绿 →
推 submodule → 主仓库 bump submodule 指针并推 → `rsync` 到本机 profile → 告诉用户
「重启后调 doctor 确认 version」。

**服务端**：`scp` 到 `dell-16-plus:C:/Users/PeiJingbo/MyCode/WeVisOne-VL-MCP/wevisone_mcp/` →
`ssh … scripts/serve.ps1 -BindHost 0.0.0.0 -TokenFile .token` 重启 → **真机跑一次调用**验证，
不能只跑单元测试。

### 7.8 交付前自检

- [ ] 改完是否验证过（真机一次调用，不是只看代码）
- [ ] 版本号是否升了，`doctor.version` 是否等于 `package.json`
- [ ] CHANGELOG 是否有一行
- [ ] 结论里是否区分了「实测通过」与「推断」

## 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-16 | v0.1 | 初始契约 |
| 2026-11-17 | v0.2 | 增 §7 生产运行与实测迭代；§0 状态改为生产实测；skill 冻结判定 |
