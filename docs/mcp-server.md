# MCP 服务器：部署、启动、注册与接入

WeVisOne-VL 感知能力的 **MCP 服务器**。任何支持 MCP 的 agent（Claude Desktop、Cline、Continue、自研客户端）都能用；同时暴露一份等价的 REST 接口给脚本和 CLI。

> 只给 DeepSeek Harness 用的原生插件请见 [dsh-plugin.md](dsh-plugin.md)。两者是**替代关系**，不要同时启用。

---

## 0. 两种角色，同一份代码

同一个 `wevisone_mcp.server` 进程有两种运行方式，**看要不要在本机跑模型**：

| 角色 | 什么时候用 | 关键变量 | 是否加载模型 |
|---|---|---|---|
| **本地模式**（local） | 这台机器就是 GPU 机 | 无 | ✅ 加载，占显存 |
| **远端模式**（remote） | 这台机器只做代理，GPU 在另一台 | `WEVISONE_REMOTE_URL` | ❌ 不加载，也不需要 torch |

远端模式下 `/mcp`、`/predict`、`/upload`、`/artifacts` **全部原样转发**给 GPU 机，
客户端分辨不出区别，也不用知道 GPU 机的令牌。

```
客户端 ──MCP/REST──> 远端模式 server（普通机器） ──HTTP──> 本地模式 server（GPU 机）
```

`wevisone_doctor` 返回的 `mode` 字段会明确告诉你当前是 `local` 还是 `remote`。

---

## 1. GPU 机：启动 WeVisOne-VL

### 1.1 准备

| 需要 | 说明 |
|---|---|
| 项目 | `wevisone_mcp` 代码 + 上游 `WeVisOne-VL` |
| 模型 | 2B 约 4.9 GB，4B 约 9.7 GB（bf16） |
| Python | 3.10+，装 torch（CUDA 版）、transformers、mcp、uvicorn、Pillow |
| 显存 | 6 GB 可跑 2B（decoder 放 CPU）；不足就用远端模式 |

```bash
# 依赖（不要装 requirements.txt 里的 vllm：多数平台没有 wheel）
pip install torch --index-url https://download.pytorch.org/whl/cu121
pip install -e /path/to/WeVisOne-VL
pip install mcp uvicorn Pillow
```

下载模型（国内可用镜像）：

```bash
export HF_ENDPOINT=https://hf-mirror.com
hf download tencent/WeVisOne-VL-2B --local-dir /models/WeVisOne-VL-2B
```

### 1.2 生成令牌（非回环监听必须）

```bash
# Linux / macOS
python -c "import secrets; print(secrets.token_hex(24))" > .token && chmod 600 .token

# Windows PowerShell（脚本会自动做，见 §3）
```

服务端从 `WEVISONE_MCP_TOKEN` 或 `WEVISONE_MCP_TOKEN_FILE` 读取；**不要把令牌写进命令行**。

### 1.3 启动

```bash
# 直接前台跑（排查时最方便）
WEVISONE_MCP_HOST=0.0.0.0 WEVISONE_MCP_PORT=8000 \
WEVISONE_MCP_TOKEN_FILE=$PWD/.token \
WEVISONE_UPSTREAM=/path/to/WeVisOne-VL \
WEVISONE_MODEL=/models/WeVisOne-VL-2B \
python -u -m wevisone_mcp.server
```

启动成功的日志：

```
model preloaded
wevisone-vl MCP on http://0.0.0.0:8000/mcp (token=on, local model)
```

### 1.4 验证

```bash
TOK=$(cat .token)
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"task":"unknown","query":""}' http://127.0.0.1:8000/predict
# → {"ok": false, "error": "ValueError: unknown task ..."}   ← 能回这条就说明是通的
```

---

## 2. 另一台机器：远端模式 MCP 服务器

**不需要 GPU、不需要 torch、不需要模型**，只装两个包。

```bash
pip install mcp uvicorn
```

```bash
WEVISONE_MCP_HOST=0.0.0.0 WEVISONE_MCP_PORT=9000 \
WEVISONE_REMOTE_URL=http://192.168.1.12:8000 \
WEVISONE_REMOTE_TOKEN=<GPU 机的令牌> \
WEVISONE_MCP_TOKEN_FILE=$PWD/.token \
python -u -m wevisone_mcp.server
```

日志：

```
remote mode: forwarding to http://192.168.1.12:8000 (no local model)
wevisone-vl MCP on http://0.0.0.0:9000/mcp (token=on, remote -> http://192.168.1.12:8000)
```

**为什么要有本机自己的令牌？** 这样外部客户端只拿到代理机的令牌，GPU 机的令牌留在这台机器上不扩散。

验证：

```bash
curl -s -X POST -H "Authorization: Bearer $(cat .token)" -H "Content-Type: application/json" \
  -d '{"task":"unknown","query":""}' http://127.0.0.1:9000/predict
```

或直接跑客户端自检：

```bash
python client_check.py --url http://127.0.0.1:9000/mcp --token $(cat .token)
```

---

## 3. 注册 / 卸载开机自启

两者都支持 install / uninstall / status，**命令相同**，只是平台不同。

### Windows

```powershell
# 开机即启（未登录也启动，需要管理员权限；任务以 SYSTEM 身份运行）
powershell -File scripts/serve.ps1 -BindHost 0.0.0.0 -TokenFile .token -AtStartup

# 登录后启动（免提权）
powershell -File scripts/serve.ps1 -BindHost 0.0.0.0 -TokenFile .token -Autostart

# 注销自启（保留任务，只删触发器）
powershell -File scripts/serve.ps1 -NoAutostart

# 只停止
powershell -File scripts/serve.ps1 -Stop

# 连计划任务一起删除
powershell -File scripts/serve.ps1 -Uninstall
```

要点：

- 自启意图记在 `<项目>/.autostart`，之后普通重启**不会**再把触发器冲掉
- `-AtStartup` 会自动给令牌文件补 `SYSTEM:(R)`，否则 SYSTEM 读不到令牌会拒绝绑定
- 远端模式的机器同样适用，只需额外设 `WEVISONE_REMOTE_URL` 环境变量（可在 `serve.ps1` 里加一行 `set`）

### Linux（systemd）

```bash
sudo ./scripts/service.sh install      # 系统级，开机启动
./scripts/service.sh install           # 用户级（自动 enable-linger，未登录也启动）
./scripts/service.sh status
sudo ./scripts/service.sh uninstall    # 用户级去掉 sudo
```

可覆盖 `WEVISONE_PYTHON` / `WEVISONE_PROJECT` / `WEVISONE_HOST` / `WEVISONE_PORT` / `WEVISONE_TOKEN_FILE`。

> Windows 不注册成「真·服务」是因为 Python 脚本本身不是 SCM 服务，需要 `nssm` 或 pywin32 包装；
> 计划任务的开机触发 + SYSTEM 身份功能等价且零依赖。Linux 的 systemd 本身就是真服务。

---

## 4. 接入各种 agent 客户端

传输统一是 **Streamable HTTP**，路径 `/mcp`，令牌放在 `Authorization: Bearer <token>`。

### 4.1 通用 mcpServers 片段（Claude Desktop 等）

`claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "wevisone": {
      "type": "streamable-http",
      "url": "http://192.168.1.12:8000/mcp",
      "headers": { "Authorization": "Bearer <token>" }
    }
  }
}
```

> 能不能用、字段名怎么叫取决于客户端版本：有的用 `type`，有的用 `transport`；
> 老版本只支持 `command`（stdio）则需要一个 shim。以客户端文档为准。

### 4.2 DeepSeek Harness（MCP 方式）

在 `~/.dsh/profiles/<profile>/cordis.patch.yml` 里：

```yaml
- insert:
    - id: mcp-wevisone
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: wevisone
        transport: streamable-http
        url: http://192.168.1.12:8000/mcp
        headers:
          Authorization: !!js '`Bearer ${process.env.WEVISONE_MCP_TOKEN || process.getBuiltinModule("node:fs").readFileSync(process.env.HOME + "/.dsh/wevisone-token", "utf8").trim()}`'
        toolCallTimeoutMs: 120000
        reconnect:
          enabled: true
```

**改完必须校验再重启**（写错会让 DSH 起不来）：

```bash
node scripts/check_dsh_yaml.mjs
```

### 4.3 自己的代码

- **MCP SDK**：连 `http://<host>:<port>/mcp`，带 Bearer 头
- **REST**：见 §5，适合脚本、批处理、CI

---

## 5. REST 接口（非 MCP 客户端用这个）

全部需要 `Authorization: Bearer <token>`。

| 方法 | 路径 | 用途 |
|---|---|---|
| `POST` | `/predict` | 跑任务，返回 JSON（与 MCP 工具同字段） |
| `POST` | `/upload` | 原始图片字节 → `upload_id` |
| `GET` | `/artifacts/<id>` | 下载 PNG 掩码 |
| `GET` | `/mcp` | MCP 端点（不含在 REST 里） |

```bash
# 一次预测（小图可直接内联 base64）
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "{\"image_base64\":\"$B64\",\"task\":\"segmentation\",\"query\":\"sofa\"}" \
  http://host:8000/predict

# 大图先上传，再用 id
ID=$(curl -s -X POST --data-binary @photo.jpg -H "Authorization: Bearer $TOK" \
  http://host:8000/upload | python3 -c 'import json,sys;print(json.load(sys.stdin)["upload_id"])')
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d "{\"upload_id\":\"$ID\",\"task\":\"matting\",\"query\":\"sofa\"}" http://host:8000/predict
```

响应形状：

```json
{
  "ok": true, "task": "segmentation", "query": "sofa", "rejected": false,
  "response": "<ref>sofa</ref><box><30><454><964><876><OBJ></box>",
  "boxes": [[0.03, 0.454, 0.964, 0.876]], "box_count": 1,
  "artifacts": [{"index": 0, "url": "/artifacts/…", "bytes": 23538, "content_type": "image/png"}],
  "artifact_count": 1, "latency_s": 4.16
}
```

- 坐标归一化 0–1；目标不存在时 `rejected: true` 且 `boxes` 为空
- 掩码不内联，只给相对 URL（10 分钟过期）
- 错误统一 `{"ok": false, "error": "..."}`

命令行客户端（只需要标准库）：

```bash
python -m wevisone_mcp.cli --endpoint http://host:8000 --token $TOK \
  predict --image a.jpg b.jpg --task segmentation --query sofa --out masks/
```

---

## 6. 环境变量总表

| 变量 | 默认 | 说明 |
|---|---|---|
| `WEVISONE_MCP_HOST` | `127.0.0.1` | 监听地址；非回环必须配令牌 |
| `WEVISONE_MCP_PORT` | `8000` | 端口 |
| `WEVISONE_MCP_TOKEN_FILE` | — | **推荐**：从文件读令牌 |
| `WEVISONE_MCP_TOKEN` | — | 直接给令牌（优先于文件） |
| `WEVISONE_REMOTE_URL` | — | 设置后进入远端模式，转发到这台 GPU 机 |
| `WEVISONE_REMOTE_TOKEN` | 同 `TOKEN` | 访问 GPU 机用的令牌 |
| `WEVISONE_REMOTE_TIMEOUT_S` | `180` | 转发超时 |
| `WEVISONE_UPSTREAM` | — | 上游 `WeVisOne-VL` 路径（本地模式） |
| `WEVISONE_MODEL` | — | 模型目录（本地模式） |
| `WEVISONE_DEVICE` | `auto` | `cuda` / `npu` / `cpu` / `mps` |
| `WEVISONE_DECODER_DEVICE` | `auto` | 像素解码器设备；小显存建议 `cpu` |
| `WEVISONE_DTYPE` | `auto` | `float16` / `bfloat16` / `float32` |
| `WEVISONE_MAX_PIXELS` | `512*32*32` | 输入缩放上限，越小越省显存 |
| `WEVISONE_MAX_NEW_TOKENS` | `512` | 单次生成上限 |
| `WEVISONE_PRELOAD` | `1` | 启动即加载模型；远端模式自动跳过 |
| `WEVISONE_UPLOAD_DIR` / `_TTL_S` | `uploads` / `600` | 上传落盘与过期 |
| `WEVISONE_ARTIFACT_DIR` / `_TTL_S` | `artifacts` / `600` | 掩码落盘与过期 |

---

## 7. 排障

| 现象 | 原因与处理 |
|---|---|
| `refusing to bind a non-loopback address without WEVISONE_MCP_TOKEN` | 监听 `0.0.0.0` 必须有令牌；给 `TOKEN_FILE` 或 `TOKEN` |
| `cannot read WEVISONE_MCP_TOKEN_FILE=...: Permission denied` | 运行身份读不到令牌（如 SYSTEM）。给对应账户读权限，或换运行身份 |
| 客户端报 `unauthorized` | 令牌不一致；轮换后客户端要重启才生效 |
| 首个请求超时（`SSE stream ended`） | 模型冷加载塞在首个调用里；保持 `PRELOAD=1` |
| 远端模式报 `unreachable` | 代理机到 GPU 机的网络/端口/令牌有问题；先在代理机上 `curl` GPU 机的 `/predict` |
| 小显存 OOM | 降 `MAX_PIXELS`、关掩码解码（用 `detection`）、或把 `DECODER_DEVICE=cpu` |
| `detection` 以前 `boxes` 为空 | 已修复：非像素任务的框会从 `response` 回退解析 |

日志：前台直接看；计划任务看 `<项目>/server.log`、`server.err`；systemd 用 `journalctl --user -u wevisone-mcp -f`。
