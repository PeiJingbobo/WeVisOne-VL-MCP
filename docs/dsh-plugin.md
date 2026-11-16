# DeepSeek Harness 原生插件：安装与配置

把 WeVisOne-VL 感知能力做成 DSH 的**原生插件**，而不是通过 MCP 客户端接入。

> 只想要 MCP 接入（或者要给别的 agent 用）请看 [mcp-server.md](mcp-server.md)。
> **两者二选一**，同时启用会出现两套同类工具。

---

## 1. 它比 MCP 版强在哪

插件跑在 **DSH 主机进程内**，所以能直接碰本地文件：

| | MCP 版 | 插件版 |
|---|---|---|
| 输入 | 先 `POST /upload`，或内联 base64 | **`image_path`，直接读本地文件** |
| 掩码 | `/artifacts/<id>` URL，自己下载 | **落本地 PNG，返回 `local_path`** |
| 模型上下文 | 少量 | 更少（连 URL 都不用拼） |
| 传输 | MCP（JSON-RPC） | 普通 REST（`/predict`、`/artifacts`） |

**它本身不跑模型**：仍然连一台 WeVisOne-VL 服务（本地模式或远端模式的 MCP 服务器都可以）。

**它不是 MCP 客户端。** 名称里的 `mcp` 指的是它连接的服务（WeVisOne-VL-MCP）。
它用 `ctx.tools.register()` 注册 DSH 原生工具，用普通 HTTP REST 通信，不经过 MCP 的 JSON-RPC。
要用 MCP 协议本身（比如给别的 agent 用），走 [mcp-server.md](mcp-server.md)。

插件同时注册一个 **`wevisone-vision` skill**，在模型动手前告诉它 11 个任务怎么选、
返回字段怎么读、有哪些坑。

---

## 2. 前置

GPU 那台机器上要有一个在跑的服务，且能从 DSH 这台机器访问到。

```bash
# 在 GPU 机上（或代理机上）确认
curl -s -X POST -H "Authorization: Bearer $TOK" -H "Content-Type: application/json" \
  -d '{"task":"unknown","query":""}' http://192.168.1.12:8000/predict
```

看到任务校验错误就说明通了。详见 [mcp-server.md §1–2](mcp-server.md)。

---

## 3. 安装

插件是通过仓库地址直装的**纯 ESM 包，零依赖、无构建步骤**（`index.js` 就在仓库根）。

```sh
dsh plugin add github:PeiJingbobo/dsh-wevisone-mcp-plugin
```

这会把它写进 profile 的 `dependencies` 与 `dsh.profile.bundles`，装完出现在插件列表里，重启 DSH 生效。

手动安装（等价，便于排查）：

```bash
PROFILE=~/.dsh/profiles/desktop      # 换成你的 profile

# package.json：
#   dependencies["dsh-wevisone-mcp-plugin"] = "github:PeiJingbobo/dsh-wevisone-mcp-plugin"
#   dsh.profile.bundles += "dsh-wevisone-mcp-plugin"

pnpm install --dir $PROFILE          # 先退出 DSH，见 §7
```

> 源码就在本仓库的 `plugin/dsh-wevisone-mcp-plugin`（git submodule）；
> 也可以 `git clone` 后用 `dsh plugin add ./dsh-wevisone-mcp-plugin` 本地安装。

### 配置：在 profile 的 `cordis.patch.yml` 里按 id 覆盖

```yaml
- id: dsh-wevisone-mcp-plugin
  config:
    endpoint: http://192.168.1.12:8000
    token: !!js '`${process.env.WEVISONE_MCP_TOKEN || process.getBuiltinModule("node:fs").readFileSync(process.env.HOME + "/.dsh/wevisone-token", "utf8").trim()}`'
    maskDir: !!js '`${process.env.HOME}/wevisone-masks`'
    timeoutMs: 180000
```

| 键 | 默认 | 说明 |
|---|---|---|
| `endpoint` | `http://127.0.0.1:8000` | 服务地址 |
| `token` | `$WEVISONE_MCP_TOKEN` | 共享令牌；建议像上面那样从 0600 文件读 |
| `maskDir` | `<cwd>/wevisone-artifacts` | 掩码落盘目录 |
| `timeoutMs` | `180000` | 单次请求超时 |

令牌文件：

```bash
scp dell-16-plus:'C:/Users/PeiJingbo/MyCode/WeVisOne-VL-MCP/.token' ~/.dsh/wevisone-token
chmod 600 ~/.dsh/wevisone-token
```

### 校验（改完配置必须做）

```bash
node scripts/check_dsh_yaml.mjs            # 默认检查 desktop profile
# OK   .../cordis.patch.yml
#      entries with a name: 7
#      Authorization renders ok (48 chars)
```

`!!js` 的值是**单引号字符串**，漏掉结尾引号会让 DSH 直接起不来（不是插件失败，是加载器拒绝）。

验证通过后**重启 DSH**。MCP 客户端的连接头在建立时固定，配置改动不会热生效。

---

## 4. 验证

重启后除了两个工具，技能目录里还应该多一个 **`wevisone-vision`**：

| 位置 | 应有的东西 |
|---|---|
| 工具列表 | `wevisone_predict`、`wevisone_doctor` |
| 技能目录 | `wevisone-vision`（描述里会提到 WeVisOne-VL 与本机图片路径） |

技能是指导材料，模型在调用前会读它。只看到工具没有技能，说明 profile 缺 `skills` 服务
（通常由 `@deepseek-ai/dsh-base` 提供）。



重启后工具列表里应出现两个**不带 `mcp__` 前缀**的工具：

| 工具 | 说明 |
|---|---|
| `wevisone_predict` | 参数 `image_path` / `upload_id` / `task` / `query` / `save_dir` |
| `wevisone_doctor` | 无参数，返回端点、令牌是否配置、掩码目录 |

让 agent 执行：

```text
wevisone_predict(image_path="/path/to/photo.jpg", task="segmentation", query="sofa")
```

返回里 `artifacts[].local_path` 是**本机**的 PNG 路径，可以直接 `read_image` 或用别的工具处理。

诊断失败先调 `wevisone_doctor`：`ok:false` 说明端点不可达或令牌不对。

---

## 5. 卸载

```bash
PROFILE=~/.dsh/profiles/desktop

# 1) 从 package.json 里删掉 dependency 与 bundles 里的条目
# 2) 删目录与 vendor 包
rm -rf $PROFILE/node_modules/@wevisone/dsh-wevisone-mcp-plugin
rm -f  $PROFILE/vendor/wevisone-dsh-wevisone-mcp-plugin-*.tgz
# 3) 删掉 cordis.patch.yml 里的 - id: dsh-wevisone-mcp-plugin 配置块
# 4) 校验并重启
node scripts/check_dsh_yaml.mjs
```

---

## 6. 和 MCP 版二选一

| 你的情况 | 选择 |
|---|---|
| 只有 DSH，且要让 agent 直接读本地图片文件 | **插件** |
| 还要给 Claude Desktop / 别的 agent / 脚本用 | **MCP** |
| 两个都要 | 装 MCP 即可，插件不再装；或反过来，让别的客户端直连 REST |

同时启用时工具名不冲突（MCP 是 `mcp__wevisone__wevisone_predict`，插件是
`wevisone_predict`），但模型会在两套同类工具间犹豫，没必要。

---

## 7. 注意事项

- **DSH 运行时不要跑 `pnpm install`**：桌面宿主持有 pnpm store 锁，你的安装会无输出地卡住。
  先退出 DSH，或按 §3 手动解包。
- **改 `cordis.patch.yml` 后必须校验**：见 §3，写错会让 DSH 起不来。
- **令牌轮换后要重启 DSH**：连接头在建立时固定。
- **插件不加载模型**：GPU 显存问题属于服务端，见 [mcp-server.md §7](mcp-server.md)。
- **不要与 `mcp-wevisone` 同时启用**：见 §6。
