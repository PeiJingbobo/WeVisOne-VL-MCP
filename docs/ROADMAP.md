# ROADMAP · WeVisOne-VL-MCP

> **唯一进度源**。任务状态、验收映射、待决问题、文档漂移都以本文件为准。
> 规则：AGENTS.md §5。会话结束必须回写。
> 版本 v0.1 | 2026-11-16

## 0. 当前状态

| 项 | 值 |
|---|---|
| 当前里程碑 | M1 MCP server 可用 |
| 当前任务 | M1-T1 完成，待 M1-T2（DSH 接入配置） |
| 阻塞项 | 无 |
| 下一里程碑 | M2 DeepSeek Harness 原生接入 |

图例：☐ 未开始 · ◐ 进行中 · ☑ 已完成（有证据） · ✗ 阻塞 · — 不适用

## 1. 使用规则

- 一轮只做一个任务；状态变更必须附证据命令与结果。
- 新任务先在本文件登记，再动手。

## 2. 里程碑与任务

### M1 MCP server 可用

| ID | 任务 | 状态 | 验收映射 | 证据 | 备注 |
|---|---|---|---|---|---|
| M1-T1 | MCP server（2 工具，Streamable HTTP，跨机可用） | ☑ | AC-01..AC-06 | 见 §3 | 2026-11-16 |
| M1-T2 | 在 DeepSeek Harness 侧登记该 MCP server | ☑ | AC-07 | 改 `~/.dsh/profiles/desktop/cordis.patch.yml` 加 `@deepseek-ai/dsh-mcp-client` 实例，**HMR 热加载，无需重启** | 2026-11-16 |

### M2 接入形态补齐

| ID | 任务 | 状态 | 验收映射 | 证据 | 备注 |
|---|---|---|---|---|---|
| M2-T1 | Python API 直连形态（无需 MCP 客户端） | ☑ | AC-11 | `client.predict` 返回 PIL 掩版 640×640；bytes 入参与 PIL 入参结果一致；坏字节返回 ok=false | 2026-11-16 |
| M2-T2 | 原生 DSH 插件：本地图入、掩码落本地 | ☑ | AC-12 | 真实 `ToolRuntime` 注册 2 工具；容器内真机分割 3347 ms，掩码 23538 B PNG 落盘 | 2026-11-16 |
| M2-T5 | CLI 形态：任意机器跑预测/体检，批量 + 掩码落盘 + `--json` | ☑ | AC-13 | 11 项 HTTP 往返测试通过；Mac 真机调 Windows GPU：3.122s，掩码 22620 B 合法 PNG | 2026-11-16 |
| M2-T6 | 令牌去硬编码 + 轮换成 48 位随机串 | ☑ | AC-14 | 旧令牌 401 / 无令牌 401 / 新令牌 200；`serve.ps1 -Rotate` 可重复执行 | 2026-11-16 |
| M2-T7 | 解决 K9：`boxes` 为空时从 `response` 回退解析坐标 | ☑ | AC-15 | 11 项新单测；真机 detection 由 `[]` 变 `[[0.03,0.454,0.964,0.876]]`，拒绝行为不变 | 2026-11-16 |
| M2-T8 | 开机自启：Windows 计划任务 + Linux systemd，均支持注册/注销/状态 | ☑ | AC-16 | Windows 真机：`MSFT_TaskBootTrigger` + SYSTEM + 活体 200；Linux 四条路径用假 systemctl 垫片验证 | 2026-11-16 |
| M2-T9 | 原生插件正式装进 desktop profile（出现在插件列表） | ☑ | AC-17 | 包已进 `dependencies` + `dsh.profile.bundles` + `node_modules`；配置按 id 注入；校验器通过 | 2026-11-16 |
| M2-T10 | 拆分文档 + MCP server 远端模式（代理到 GPU 机） | ☑ | AC-18 | 新增 `docs/mcp-server.md`、`docs/dsh-plugin.md`、README 改索引；远端转发 6 项单测通过 | 2026-11-16 |
| M2-T11 | 双仓库管理：主仓库 + 插件子模块，插件支持仓库地址直装 | ☑ | AC-19 | `dsh plugin add github:PeiJingbobo/dsh-wevisone-mcp-plugin`；包名去 `@wevisone`；index.js 在仓库根 | 2026-11-16 |
| M2-T12 | 让模型优先用工具而非自带视觉（三层：描述/提醒/skill） | ☑ | AC-20 | 真实会话验证：空上下文先加载 skill 再调工具，未用自带视觉答题 | 2026-11-17 |
| M2-T13 | 抠像会话复盘后的四项修：save_dir 生效、homedir 跨平台、任务选择、合成配方 | ☑ | AC-21 | `test/save-dir.mjs` 9 项断言；真机 segmentation+save_dir 7.2s 落盘 | 2026-11-17 |
| M2-T14 | 插件版本可见：每次改动升版本号，`doctor` 暴露 version | ☑ | AC-22 | 0.1.0 → 0.3.0；CHANGELOG 记录三批变更；单测断言 doctor.version == package.json | 2026-11-17 |
| M2-T15 | 掩码统计进 predict 响应，配套「用数字校验」指导 | ☑ | AC-23 | 真机返回 coverage/alpha 极值/bbox/触边；skill 限定 read_image 仅三种例外 | 2026-11-17 |
| M2-T16 | 抠像成本治理：读图上限、runtime python、原位置二义性、undefined 目录防御 | ☑ | AC-24 | 会话复盘：6 次读图 + 1 次 PIL 失败 → 三项规则 + 插件兜底 | 2026-11-17 |
| AC-25 | skill 不再无限增长 | ☑ | 冻结注记 + AGENTS 三条判定（改措辞可防/需会话证据/净增≤300B）| 
| M2-T17 | skill 冻结：只对新类型失败加规则 | ☑ | AC-25 | 基线 v0.6.1 / 9,019 字节；判定标准三条写入 AGENTS.md | 2026-11-17 |
| M2-T3 | 解决 K5：`POST /upload` + `upload_id` 入参 | ☑ | AC-08 | 25 单测；上传 228KB 原图 → `upload_id` → DSH 原生工具分割成功 4.23s | 2026-11-16 |
| M2-T4 | 解决 K6：掩码落盘 + `GET /artifacts/<id>`，响应只给相对 URL | ☑ | AC-10 | 响应由约 31 KB base64 降到约 250 B；下载到合法 PNG 640×640 | 2026-11-16 |

## 3. 验收场景映射

| ID | 场景 | 结论 | 证据 |
|---|---|---|---|
| AC-01 | shaping 纯函数单测在无 GPU 机器通过 | ☑ | `python3 -m unittest discover -s tests -v` → 13 passed, 1 skipped |
| AC-02 | MCP 握手 + 工具发现 + doctor | ☑ | `client_check.py --url http://127.0.0.1:8000/mcp` → 2 tools, doctor ok |
| AC-03 | 本机端到端分割（含 alpha PNG） | ☑ | predict segmentation sofa → 1 box, 1 mask, 3.692s |
| AC-04 | 跨机调用（Mac → 192.168.1.12）带令牌 | ☑ | predict → ok, box_count=1, mask_count=1, 3.002s |
| AC-05 | 冷启动后首次调用可用（预加载生效） | ☑ | 重启后首调 `model_loaded: true`, 3.786s |
| AC-06 | 拒绝能力未被破坏 | ☑ | `referring` + 不存在的目标 → `rejected=true` |
| AC-07 | DSH 中可见 `wevisone_*` 工具 | ☑ | `list_mcp_resources(wevisone)` 返回 serverInfo；`mcp__wevisone__wevisone_doctor` 返回远端真实状态（`model_loaded=true`） |
| AC-08 | DSH 原生工具用 `upload_id` 跑通一次预测 | ☑ | `upload_id=2a0f031b…` + segmentation → `ok=true`, box_count=1, mask_count=1, 4.234s（上下文内无 base64） |
| AC-09 | 上传端点鉴权与体积限制 | ☑ | 无令牌 POST `/upload` → 401；有令牌 → `upload_id` + bytes |
| AC-10 | 掩码 URL 可下载且鉴权正确 | ☑ | 带令牌 200 + 23538 B + `PNG 640x640 8-bit grayscale`；无令牌 401；穿越 id 404；不存在 id 404 |
| AC-11 | 进程内 Python API 可用 | ☑ | `scripts/check_python_api.py` → 1 框 + `L (640,640)` 掩版，8.058s（含冷加载）；bytes 入参 parity OK；坏字节 `ok=false` |
| AC-12 | DSH 原生插件被真实注册表接受并端到端可用 | ☑ | Docker 内用 `@deepseek-ai/dsh-tools` 的 `ToolRuntime` 注册 `wevisone_predict`/`wevisone_doctor`；真机分割 3347 ms；落盘 `PNG magic OK` 23538 B |
| AC-13 | CLI 可用且行为正确 | ☑ | `tests/test_cli.py` 11 项（成功/拒绝/服务端错误/缺文件/批量/`--json`/令牌/退出码）；Mac→Windows 真机 `boxes=1`、`3.122s`、`PNG 640x640` |
| AC-14 | 令牌不出现在任何配置文件/启动参数 | ☑ | `serve.ps1` 任务参数只含 `.token` 路径；`cordis.patch.yml` 中旧令牌字面量出现 0 次（已改为读 0600 文件）；轮换后旧令牌 401 |
| AC-15 | `detection` 等非像素任务也能拿到框 | ☑ | 真机 `detection` 返回 1 框；`segmentation` 仍 1 框 + 1 掩码且两者对齐；`unicorn` 仍 `rejected: true` / `boxes: []` |
| AC-16 | 两平台都能注册/注销开机自启 | ☑ | Windows `-AtStartup` → `MSFT_TaskBootTrigger`/SYSTEM/端口活；`-NoAutostart` → 触发器归零；普通重启不冲掉自启。Linux install/uninstall/status/提权守卫四路径通过 |
| AC-17 | 插件出现在 profile 插件列表 | ☑ | 重启后宿主暴露 `wevisone_predict`/`wevisone_doctor`（带 `image_path` 参数的插件版 schema），证明 bundle 已装载并注册成功 |
| AC-18 | MCP 文档可独立部署；远端模式可用 | ☑ | 真机 E2E：9000 代理→8000 本地服务，`predict ok=True boxes=[0.03,0.454,0.964,0.876] 6.07s`、`artifact HTTP 200 / 23538 B`、`upload ok=True 228868 B`； `docs/mcp-server.md` 覆盖 GPU 机启动/远端代理/自启注册卸载/各 agent 接入/REST/CLI/环境变量/排障；`tests/test_remote_mode.py` 6 项通过（转发、错误透传、本地校验先行、artifacts 拉取、不可达提示） |
| AC-19 | 两仓库可克隆、插件可按仓库地址安装 | ☑ | 主仓库 30 个文件 + 子模块指针已推送；插件仓库 6 个文件（index.js 在根、零依赖）；本地 profile 切到新包名后解析与加载均通过 |
| AC-20 | 工具优先于自带视觉 | ☑ | 会话日志：第 1 步 `skill` + `wevisone_doctor`，第 2 步直接 `wevisone_predict`；三次 `read_image` 均为校验产物 |
| AC-21 | 抠像四项修全部生效 | ☑ | `save_dir` 覆盖 maskDir（单测 9 项 + 真机 7.2s）；默认目录改 `os.homedir()`；skill 增 segmentation 优先、多掩码取最大、`putalpha` 配方 |
| AC-22 | 能判断插件是否真的重装 | ☑ | `wevisone_doctor` 返回 `version`；`test/save-dir.mjs` 断言与 `package.json` 一致（11 项断言全过）；AGENTS 立为规则 |
| AC-23 | 掩码可用性可只靠文本判断 | ☑ | `stats` 含 coverage/alpha/bbox/touches_edge；skill 给出区间与三例外 |
| AC-24 | 抠像读图 ≤1 次、无 python 选错、原位置二义性一次覆盖 | ☑ | 0.4.1 skill + `maskDir` 含 `undefined` 时警告并回退（已用假 ctx 验证） |

## 4. UI 验收映射

- 不适用（本项目无界面）。

## 5. 待决问题

| ID | 问题 | 阻塞任务 | 默认方案 | 状态 |
|---|---|---|---|---|
| Q1 | DSH 自定义 MCP server 的配置入口是什么（仅见 penpot kit 的 `config.json` 形态） | M1-T2 | 按 penpot 形态提供 `mcp.serverName/transport/url/headers` 配置，供 DSH 读取 | 待确认 |
| Q2 | 跨机是否需要长期固定令牌轮换 | 无 | 首版固定令牌，内网使用 | 开放 |

## 6. 会话日志

| 日期 | 执行者 | 做了什么 | 证据 | 下一步 |
|---|---|---|---|---|
| 2026-11-16 | DSH agent | 建契约 + M1-T1（shaping/server/client_check/serve.ps1），部署到 dell-16-plus，跨机验证通过 | §3 AC-01..AC-06 | M1-T2 |
| 2026-11-16 | DSH agent | M1-T2：DSH `cordis.patch.yml` 注册 MCP 实例（HMR 热加载，无需重启）；发现 K5（base64 载荷不可行） | AC-07 通过；AC-08 阻塞 | M2-T3 |
| 2026-11-16 | DSH agent | M2-T3：`POST /upload` + `upload_id`；25 单测；DSH 原生工具用 upload_id 分割成功 | AC-08/AC-09 通过 | K6 观察 |
| 2026-11-16 | DSH agent | M2-T4：掩码改落盘 + `/artifacts/<id>`；模型上下文不再承载图像字节 | AC-10 通过 | M2-T1 / M2-T2 待排 |
| 2026-11-16 | DSH agent | M2-T1：`wevisone_mcp.client` 进程内 API（PIL 入参、PIL 掩版返回） | AC-11 通过 | M2-T2 / K7 待排 |
| 2026-11-16 | DSH agent | M2-T2：新增 `POST /predict` REST + 原生插件 + Docker 调试环境 | AC-12 通过；M2 全部完成 | K8 待排 |
| 2026-11-16 | DSH agent | M2-T5：`python -m wevisone_mcp.cli`（仅标准库，走 REST） | AC-13 通过 | K9 待排 |
| 2026-11-16 | DSH agent | M2-T6：`WEVISONE_MCP_TOKEN_FILE` + `serve.ps1 -TokenFile/-Rotate` + DSH 配置改为读 0600 文件 | AC-14 通过；**待用户重启 DSH 后复验原生工具** | Q3 关闭 |
| 2026-11-16 | DSH agent | M2-T7：`shaping.parse_boxes()` 修复坐标口径 | AC-15 通过；K9 关闭 | 开机自启待排 |
| 2026-11-16 | DSH agent | M2-T8：`serve.ps1` 开机/登录触发器 + `.autostart` 标记；新增 `scripts/service.sh` | AC-16 通过 | 全部里程碑完成 |
| 2026-11-16 | DSH agent | **事故**：`!!js` 单引号漏闭合导致 DSH 启动失败；修复配置 + 新增 `scripts/check_dsh_yaml.mjs` 校验器 | K11 登记；配置已用真实 YAML 解析器验证 | 待用户重启复验 |
| 2026-11-16 | DSH agent | M2-T9：插件装成 profile bundle；插件改为零依赖普通定义对象 | 校验通过；K12 登记；待重启复验 |
| 2026-11-16 | DSH agent | M2-T10：MCP 远端模式 + 两份独立文档 + README 索引化 | AC-18 通过 | 待真机端到端复验 |
| 2026-11-16 | DSH agent | M2-T11：主仓库推送、插件仓库独立、子模块挂载、包名改名 | AC-19 通过；待用户重启验证插件仍在 |
| 2026-11-17 | DSH agent | M2-T12/T13：工具优先三层施压 + 抠像四项修 | AC-20/AC-21 通过；K13 登记 |

## 7. 文档漂移与实现偏差

| 编号 | 现象 | 冲突双方 | 当前裁决 | 依据 | 阻塞任务 |
|---|---|---|---|---|---|
| D1 | AGENTS.md §1.3 原写「task 枚举不重复定义」，实现为本地镜像 + 漂移测试 | 契约 / 实现 | 改为「本地镜像 + `test_tasks_match_upstream` 守卫」 | 避免 shaping 在 Mac 上依赖上游重依赖 | 无 |

## 8. 已知问题与技术债

| ID | 问题 | 影响 | 计划 |
|---|---|---|---|
| K1 | 冷启动若落在工具调用内（约 7s），客户端 SSE 流会被掐断，报 `SSE stream ended without a response` | 首次调用失败 | 已修：启动预加载（`WEVISONE_PRELOAD`，默认开） |
| K2 | Python 输出重定向到文件时默认块缓冲，`server.log` 长时间为空 | 排查困难 | 已修：部署脚本改用 `python -u` |
| K3 | 像素结果以 base64 返回，多目标时响应体线性增长 | 大图/多目标变慢 | 观察；需要时可加「只返回 box、按需取 mask」 |
| K4 | 6GB 显存下推理串行 | 并发受限 | 需要并发时换 24GB 卡并去掉串行锁 |
| K5 | ~~base64 图像载荷必须由模型自己生成进上下文~~ **已解决（M2-T3）**：改为 `POST /upload` + `upload_id` | — | 保留 `image_base64` 仅供程序化小客户端 |
| K6 | ~~`mask_pngs` 以 base64 回传，很吃上下文~~ **已解决（M2-T4）**：掩码落盘，响应只给 `/artifacts/<id>` 相对 URL | — | 响应体积从约 31 KB 降到约 250 B |
| K7 | `client.py` 与 MCP 服务同时运行会在 6GB 卡上 OOM（各 4.9 GB 主干） | 只能用其一 | 文档已写明；换 24GB 卡后自然消失 |
| K8 | 插件与 `mcp-wevisone` 同时启用会出现两组同类工具 | 模型困惑 | 插件 README 要求二选一；未加互斥检测 |
| K9 | ~~`detection` 的 `boxes` 恒为空~~ **已解决（M2-T7）**：`shaping.parse_boxes()` 回退解析，正则与上游重复一份，注释标明来源行号 | — | 像素任务不回退，避免 `boxes` 与 `artifacts` 失配 |
| K10 | 改 `cordis.patch.yml` 后 MCP 工具的 headers 不更新，需重启 DSH | 轮换令牌后必须手动重启客户端 | `dsh-mcp-client:47` 在连接建立时固定 headers，loader 不 watch 文件。文档已写明；未做自动重启 |
| K11 | 手改 `cordis.patch.yml` 出错会让 DSH 直接起不来（不是插件失败，是加载器拒绝） | 一次笔误就要用户手忙脚乱 | 已加 `scripts/check_dsh_yaml.mjs`：改完先跑，正反用例都验过 |
| K12 | DSH 运行时跑 `pnpm install` 会无输出卡死（桌面宿主持有 pnpm store 锁） | 装插件看起来像挂了 | 已改为手动解包安装；README 写明运行时不要用 pnpm |
| K13 | `matting` 会对每个 `<OBJ>` 解一张掩码，单次可能数十秒 | 多实例图慢 | skill 已引导单目标用 `segmentation`；未加目标数上限 |

## 9. 变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-11-16 | v0.1 | 初始进度源，M1-T1 完成 |
