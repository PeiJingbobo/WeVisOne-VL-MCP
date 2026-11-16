# WeVisOne-VL-MCP

把腾讯 [WeVisOne-VL](https://github.com/Tencent/WeVisOne-VL) 的视觉感知能力（检测 / 指代 / 计数 / OCR / 分割 / 抠图等 11 个任务）封装成 **MCP 服务器**，并提供 Python、命令行、REST、DSH 原生插件四种接入方式。

```
视觉模型（GPU 机） ──> wevisone_mcp.server ──> MCP 客户端 / REST / CLI / DSH 插件
```

同一份 server 有两种角色：**本地模式**直接加载模型；**远端模式**只做转发（不装 torch），让任意机器代理到 GPU 机。

---

## 仓库

| 仓库 | 内容 |
|---|---|
| [PeiJingbobo/WeVisOne-VL-MCP](https://github.com/PeiJingbobo/WeVisOne-VL-MCP) | 本仓库：MCP 服务器、CLI、Python API、脚本、文档 |
| [PeiJingbobo/dsh-wevisone-mcp-plugin](https://github.com/PeiJingbobo/dsh-wevisone-mcp-plugin) | DSH 原生插件（git submodule，位于 `plugin/dsh-wevisone-mcp-plugin`） |

```sh
git clone --recurse-submodules https://github.com/PeiJingbobo/WeVisOne-VL-MCP.git

# 插件直接按仓库地址安装
dsh plugin add github:PeiJingbobo/dsh-wevisone-mcp-plugin
```

## 文档

| 文档 | 内容 |
|---|---|
| **[docs/mcp-server.md](docs/mcp-server.md)** | MCP 服务器：GPU 机启动、远端模式、开机自启注册/卸载、**接入各种 agent 客户端**、REST 与 CLI、环境变量、排障 |
| **[docs/dsh-plugin.md](docs/dsh-plugin.md)** | DeepSeek Harness 原生插件：安装、配置、验证、卸载、与 MCP 版二选一 |
| [docs/ROADMAP.md](docs/ROADMAP.md) | 任务、验收、已知问题（唯一进度来源） |
| [AGENTS.md](AGENTS.md) | 工程契约：不变量、约束、目录职责 |
| [docs/adr/](docs/adr/) | 架构决策记录 |

---

## 快速开始

### 有 GPU 的机器（本地模式）

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -e /path/to/WeVisOne-VL && pip install mcp uvicorn Pillow

python -c "import secrets; print(secrets.token_hex(24))" > .token && chmod 600 .token

WEVISONE_MCP_HOST=0.0.0.0 WEVISONE_MCP_TOKEN_FILE=$PWD/.token \
WEVISONE_UPSTREAM=/path/to/WeVisOne-VL WEVISONE_MODEL=/models/WeVisOne-VL-2B \
python -u -m wevisone_mcp.server
```

### 任意其他机器（远端模式，不需要 GPU）

```bash
pip install mcp uvicorn
python -c "import secrets; print(secrets.token_hex(24))" > .token && chmod 600 .token

WEVISONE_MCP_HOST=0.0.0.0 WEVISONE_MCP_TOKEN_FILE=$PWD/.token \
WEVISONE_REMOTE_URL=http://192.168.1.12:8000 WEVISONE_REMOTE_TOKEN=<GPU 机的令牌> \
python -u -m wevisone_mcp.server
```

### 验证

```bash
curl -s -X POST -H "Authorization: Bearer $(cat .token)" -H "Content-Type: application/json" \
  -d '{"task":"unknown","query":""}' http://127.0.0.1:8000/predict
# → {"ok": false, "error": "ValueError: unknown task ..."}   ← 能回这条就通了
```

接入客户端、注册自启、完整参数见 [docs/mcp-server.md](docs/mcp-server.md)。

---

## 四种接入方式

| 方式 | 适合 | 入口 | 详情 |
|---|---|---|---|
| **MCP** | 任意支持 MCP 的 agent | `http://<host>:8000/mcp` | [mcp-server.md §4](docs/mcp-server.md) |
| **REST** | 脚本、CI、批处理 | `POST /predict` | [mcp-server.md §5](docs/mcp-server.md) |
| **CLI** | 手动验证、批量跑图 | `python -m wevisone_mcp.cli` | [mcp-server.md §5](docs/mcp-server.md) |
| **Python 直连** | 同机脚本，要 PIL 对象 | `from wevisone_mcp import client` | 见 `wevisone_mcp/client.py` |
| **DSH 原生插件** | 让 agent 直接读本地图片 | `dsh plugin add github:PeiJingbobo/dsh-wevisone-mcp-plugin` | [dsh-plugin.md](docs/dsh-plugin.md) |

MCP / REST / CLI 三者共用同一套服务端实现；插件是替代方案，不要与 MCP 同时启用。

---

## 目录

```
wevisone_mcp/
  shaping.py     纯函数：入参校验 + 结果整形（无 torch，可在无 GPU 机器测试）
  uploads.py     upload_id 签发/解析/过期清理（仅标准库）
  client.py      进程内 Python API（返回 PIL 掩版）
  cli.py         命令行客户端（仅标准库，走 REST）
  server.py      MCP 工具面 + 模型单例 + /upload + /predict + /artifacts + 远端转发
plugin/          DSH 原生插件（零依赖）+ Docker 调试环境
scripts/
  serve.ps1          Windows 计划任务：启动/停止/开机自启/注销
  service.sh         Linux systemd：安装/卸载/状态
  check_dsh_yaml.mjs 改 DSH 配置后必跑的校验器
tests/               单元测试（无 GPU 也能跑大部分）
docs/                部署与接入文档、ROADMAP、ADR
```

---

## 安全要点

1. **非回环监听必须配令牌**，否则服务拒绝启动。
2. **令牌只从环境变量或 0600 文件读**，不写进命令行、计划任务参数或 profile 配置。
3. **令牌是挡路人不是认证系统**：防同网段误用，防不了定向攻击。要暴露公网请自行加 TLS + 真正的鉴权。

详见 [docs/mcp-server.md §1.2](docs/mcp-server.md) 与 `AGENTS.md` 的不变量 I-05 / I-07。

---

## 已知限制

- 6 GB 显存跑 2B 需要把像素解码器放 CPU（默认已如此）；4B 需要更大显存
- Python 直连（`wevisone_mcp.client`）**不能与 MCP 服务同时运行**：两份主干超出 6 GB
- 掩码与上传文件默认 10 分钟过期
- 完整列表见 [docs/ROADMAP.md](docs/ROADMAP.md) 的 K1–K12
