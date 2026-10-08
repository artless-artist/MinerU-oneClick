---
name: mineru-portable
description: 用本机已解压的 MinerU 便携整合包解析本地文档——PDF、扫描件与图片、Word、PPT、Excel、RTF、OpenDocument、EPUB、OFD、HTML、MHTML、CSV，输出 Markdown / 结构化 JSON / 图片包，全程离线、免安装、模型随包自带。当用户要求阅读、解析、OCR、转换文档，提取表格或公式，或用 AI Agent 直接驱动 MinerU（而不是本人开 WebUI、不手动敲命令）时使用。只要本机存在 MinerU 便携包（目录里有 启动MinerU.bat），就优先于通用 PDF 解析器与各类 OCR 库，除非用户明确指定别的工具、格式不受支持、或整合包不可用。
---

# MinerU 便携整合包（Agent 适配版）

<!-- ===========================================================================
     安装时可改：把下面 KIT_ROOT 的 <KIT> 换成整合包的实际路径（例如 D:\Program\MinerU），
     Agent 就不必再探测或反问。保持 <KIT> 不变时，Agent 按 §0 的步骤自动定位。
     =========================================================================== -->

**KIT_ROOT: `<KIT>`**

本文件是官方 [`skills/mineru/SKILL.md`](https://github.com/opendatalab/MinerU/tree/master/skills/mineru) 的**便携包适配版**，对应 **MinerU 4.0.10**。

与官方版的区别只有三处，其余规则一致：

1. **没有安装步骤**。整合包自带便携 Python 与模型，直接调用包内命令，不要尝试 pip / uv / pipx 安装。
2. **命令要走包内的调用形式**（见 §1），因为整合包可能被解压到任意目录，PATH 里没有 `mineru`。
3. **有状态的文档库（doclib）路线在本包里当前不可用**（见 §8）。主力走无状态的 `mineru-kit parse`。

MinerU 把本地文档解析成可读内容，供 Agent 阅读、检索与引用。它**不是** RAG 框架、向量库或「与文档对话」应用。

## 0. 先定位整合包根目录

下文用 `<KIT>` 表示整合包根目录，即**包含 `启动MinerU.bat` 的那个文件夹**。每个会话开始前先解析一次，之后复用：

1. 看本文件开头的 `KIT_ROOT` 行——若已经写成具体路径（不是 `<KIT>`），直接用它。
2. 否则若 `本文件所在目录/../../启动MinerU.bat` 存在，`<KIT>` 就是 `本文件所在目录/../..`（skill 还在包内时的情形）。
3. 否则若 `本文件所在目录/../../app/bin/mineru-kit.bat` 存在，同上。
4. 都不成立（skill 被复制到了别处的 skills 目录），**不要猜**：问用户整合包解压在哪个目录，拿到后本次会话记住即可。

验证一次就够：

```bash
ls "<KIT>/app/bin/mineru-kit.bat"     # 存在即定位正确
```

> 安装到全局 skills 目录时，建议顺手把本文件顶部的 `KIT_ROOT` 改成实际路径（例如 `KIT_ROOT: D:\Program\MinerU`），以后就不用再问、也不用探测。

## 1. 调用形式

包内命令都通过「便携解释器 + `app/cli.py` 转发器」调用，它会把 `MINERU_HOME`、`TEMP`、`APPDATA` 等可写路径隔离进包内，因此**不要自己去设这些环境变量**。

**首选形式（Git Bash / cmd / PowerShell 通用，引号最稳）**：

```bash
PYTHONUTF8=1 "<KIT>/runtime/python/python.exe" "<KIT>/app/cli.py" mineru-kit parse "<输入>" -o "<输出目录>" --tier <档位> -f <格式>
```

**等价形式（批处理外壳，人类双击/菜单用的那个）**：

```bat
"<KIT>\app\bin\mineru-kit.bat" parse "<输入>" -o "<输出目录>" --tier <档位> -f <格式>
```

在 Git Bash 里调用 bat 需要 `cmd //c '...'`，且路径含空格或需要内嵌引号时容易出错——**Agent 请优先用首选形式**。

包内可用的外壳（都在 `<KIT>\app\bin\`）：`mineru.bat`、`mineru-kit.bat`、`mineru-api.bat`、`mineru-router.bat`、`mineru-webui.bat`、`mineru-openai-server.bat`、`mineru-models-download.bat`。

**不要用** `<KIT>\runtime\python\Scripts\*.exe`：pip 生成的外壳内嵌了安装时的绝对路径，整合包一旦搬移就会失效。

## 2. 决策树

接到需求先看这里：

1. 用户给了文件/目录路径，要内容 → 用 `mineru-kit parse`（§3）。纯文本格式（`.txt`/`.md`/`.rst`/`.tex`）直接读源文件，不要解析。
2. 用户要批量处理一个文件夹 → 直接把目录当输入传给 `mineru-kit parse`（§3.3）。
3. 用户要长期、程序化地反复调用（脚本、服务、自身就是程序）→ 起 `mineru-kit api-server` 走 HTTP（§4）。
4. 用户要图形界面 → 让他双击 `启动MinerU.bat` 选菜单 `[1]`，或跑 `mineru-kit webui`。这不是 Agent 该走的路径。
5. 用户要管理 / 补下模型 → `mineru-kit models`（§6）。
6. 用户想要 locator 续读、库内检索、watch、cleanup 等 → 见 §8，本包当前不可用，如实告知并提供替代。
7. 用户要远程解析 → 见 §7，**必须先征得明确同意**。

## 3. 主力路径：一次性解析

`mineru-kit parse` 是无状态的：给文件（或目录），出产物，进程结束。不依赖后台服务，因此在便携包里最可靠。

### 3.1 常用命令

```bash
# 最常用：整篇解析成 zip（markdown + images/ 外置图片）
PYTHONUTF8=1 "<KIT>/runtime/python/python.exe" "<KIT>/app/cli.py" mineru-kit parse "<文档.pdf>" -o "<KIT>/output" --tier basic -f zip

# 纯文字为主的文档：直接落一个 .md，agent 可直接读
... mineru-kit parse "<文档.pdf>" -o "<KIT>/output" --tier basic -f markdown

# 只要结构、不要图片：结构化 JSON
... mineru-kit parse "<文档.pdf>" -o "<KIT>/output" --tier basic -f middle_json

# 只解析指定页（PDF 专用）
... mineru-kit parse "<文档.pdf>" -o "<KIT>/output" --tier basic -f zip -p "1-10"

# 扫描件强制走 OCR
... mineru-kit parse "<扫描件.pdf>" -o "<KIT>/output" --tier basic -f zip --ocr-mode ocr
```

### 3.2 参数

| 参数 | 说明 |
|---|---|
| `inputs`（位置参数） | 一个或多个文件 / 目录路径，必填 |
| `-o, --output` | **输出目录**（不是文件），必填 |
| `-f, --format` | `markdown`（默认）/ `middle_json` / `zip` |
| `--tier` | `flash` / `basic` / `standard` / `advanced`，见 §5 |
| `-p, --pages` | PDF 页码，如 `1-5,8`、`r3-r1`（倒数页码）、`all`；默认全部页面 |
| `--ocr-mode` | `auto`（默认）/ `txt` / `ocr` |
| `--disable-image-analysis` | 关闭图像分析 |
| `-v, --verbose` | 详细输出 |
| `--remote` / `--remote-url` / `--api-key` | 走远程解析，见 §7 |

**务必显式传 `--tier`**：省略时它默认按 `standard` 走，会尝试加载版面 VLM；只装了 basic 模型的机器上会直接失败。

### 3.3 产物去哪、怎么读

输出文件名 = **输入文件主名 + 格式后缀**，全部落在 `-o` 指定的同一个目录里：

| 输入 | `-f markdown` | `-f zip` | `-f middle_json` |
|---|---|---|---|
| `报告.pdf` | `报告.md` | `报告.zip` | `报告.json` |
| 目录 `./paper/`（含 a.pdf、b.pdf） | `a.md`、`b.md` | `a.zip`、`b.zip` | `a.json`、`b.json` |

- **`zip` 里是 `markdown.md` + `images/`**，正文以相对路径引用图片。**推荐默认用 `zip`**：内容完整，且不会把图片的 base64 灌进上下文。
- **`markdown` 会把图片以 base64 内联在正文里**。文档含图时 `.md` 会急剧膨胀（常见几十 MB），除非确认是纯文字，否则别用这个格式——真要读，改用 `zip` 解出 `markdown.md`。
- **`middle_json`** 是结构化结果，不含图片数据，适合二次开发或要精确取块结构。
- 输出目录建议用 `<KIT>/output`（包内约定目录，且已在 `.gitignore` 里）。

读结果的建议顺序：先读 `.md` 正文；需要表格/公式/版面的视觉证据时，再去看 `images/` 里的裁图。

### 3.4 成功与失败的判据

`mineru-kit parse` **没有 `--json`**，不要期待结构化输出：

- **成功**：退出码 `0`，且 `-o` 目录里出现了产物文件。日志里会有 `已解析 N 个输入。`
- **失败**：退出码 `1`，stderr 上是中文错误行，形如 `错误: 不支持的文件类型: <路径>` 或 `错误: <路径>`。
- stdout/stderr 里混着进度条（`Layout Predict`、`OCR-det`、`VLM Predict`）和 `INFO` 日志，**不要把它们当结构化输出解析**，也不要整段贴给用户。

## 4. 可选路径：常驻 HTTP 服务

需要反复调用、或调用方本身就是程序时，起一个本地 API 服务比反复启动进程更划算：

```bash
PYTHONUTF8=1 "<KIT>/runtime/python/python.exe" "<KIT>/app/cli.py" mineru-kit api-server --host 127.0.0.1 --port 8000 --tier standard
```

- 默认监听 `127.0.0.1:8000`；`--tier` 是**服务能力档位**（`flash` / `basic` / `standard`），决定对外广播哪些解析档位，不是单次请求的档位。
- 起来后访问 `http://127.0.0.1:8000/docs` 有 OpenAPI 文档，可直接发 HTTP 请求。
- 建议用 `--port`（而非默认 8000）避开常见占用；`--allow-local-source` 仅在本机可信环境下按需开启。
- 这条路径**不依赖 SQLite 文档库**，因此不受 §8 的缺陷影响。
- 用完记得停掉进程，不要留着长期占用端口。

## 5. 档位（tier）

档位控制解析**质量、速度、算力与所需模型**。

### 5.1 四档对照

| 档位 | 中文名 | 需要什么模型 | 特点 |
|---|---|---|---|
| `flash` | 极速解析 | 只要 ONNX 小模型 | 最快、质量最低。只用于预览 / 索引 / 初筛，**不作为最终阅读质量** |
| `basic` | 基础解析 | ONNX 小模型（包内约 0.9 GB） | 快、省显存。纯文本与简单排版效果接近 standard；无版面 VLM |
| `standard` | 标准解析 | 小模型 **+ 版面 VLM**（合计约 2.1 GB） | 默认质量档。公式、表格、多栏排版更准 |
| `advanced` | 高级解析 | 同 `standard`（只是多花推理算力） | 最难文档、最高质量、最慢 |

`flash` 与 `basic` **不需要版面 VLM**；`standard` 与 `advanced` 需要。以 Office / HTML / MHTML / CSV / EPUB / OFD 为输入时，本地固定按 `flash` 路线解析，档位影响很小。

### 5.2 判断本机哪一档可用

```bash
# 退出码 0 即该档可用；非 0 说明缺模型
... mineru-kit models verify --tier basic
... mineru-kit models verify --tier standard

# 人读：列出各仓库是否就绪、每个档位对应哪些仓库
... mineru-kit models show
```

**选档位的规则**：

1. 用户明确指定了档位 → 听用户的（若该档不可用，如实说明并给替代）。
2. 否则若 `<KIT>` 路径含非 ASCII 字符（中文、日文等）→ **只能用 `basic`**，见 §5.4。
3. 否则若 `models verify --tier standard` 退出码为 0 → 用 `standard`。
4. 否则 → 用 `basic`。

### 5.3 首次向用户解释档位时

不要让用户面对光秃秃的档位名。第一次需要在对话里做档位选择时，用一两句话说明：**档位决定解析质量、速度和算力**，然后给出本机实际可用的档位及取舍，并基于用户的目标（要准还是要快）推荐一个、说明理由。用中文沟通时，首次提到档位请把中文名和标识符一起写，例如 标准解析（`standard`）。

### 5.4 便携包特有的路径限制

整合包的**根目录路径必须是纯 ASCII**（可以含空格）。`standard` / `advanced` / `flash` 依赖 llama.cpp 的原生库，它在 Windows 上打不开含非 ASCII 字符的模型路径，会抛出：

```text
RuntimeError: No mapping for the Unicode character exists in the target multi-byte code page.
```

这是打包形态的固有限制，**不是 bug**：

- 判断方法：看 `<KIT>` 路径里有没有非 ASCII 字符。**与被解析文档的路径无关**——文档路径含中文完全没问题。
- 后果：此时只能解析成 `flash` / `basic`；包内菜单会自动降级并给出提示。
- 正确应对：改用 `--tier basic`；或让用户把整个文件夹移到纯英文路径（如 `D:\MinerU`）后重试。**不要**试图改上游源码绕过。

## 6. 模型管理

```bash
... mineru-kit models show                    # 查看后端、各仓库就绪状态、档位构成
... mineru-kit models verify --tier basic     # 校验某档所需模型是否齐全
... mineru-kit models download --tier basic   # 下载某档所需模型
```

规则：

- **下载是按档位精确的**：`--tier basic` 只会下 ONNX 小模型，**不会**顺带下版面 VLM（上游依据 `resolved_tier` 决定是否追加 VLM 仓库）。只想要 basic 的用户可以放心跑补齐。
- 下载需要联网，模型来自 ModelScope（包内已默认国内源）。
- 用户也可以双击 `启动MinerU.bat` 用菜单 `[5]` 交互式补齐——那不属于 Agent 的活。
- 整合包的档位偏好记在 `<KIT>/data/models/.tier_choice`（一行 `basic` 或 `standard`）。需要知道"用户平时用哪档"时读它；它**不等于**本次该用的档位，仍按 §5.2 的规则判断。

## 7. 隐私规则

MinerU 是隐私优先的。

- 默认**全部本地解析**。只有显式给了 `--remote`，文档才会被上传。
- **上传前必须征得用户明确同意**，并且在对话里说清"这会把文档发到 mineru.net 官方服务"。用户没有同意，就不要加 `--remote`。
- 本地解析失败**不得**静默降级到远程。
- 远程失败而本地能满足时，可以退回本地。
- 涉及敏感、机密、法务、医疗、财务、个人或专有内容的请求，**默认留在本地**，除非用户给出明确的远程许可。
- 不要打印整合包里的密钥类配置。

需要远程时：

```bash
... mineru-kit parse "<文档.pdf>" -o "<KIT>/output" -f zip --remote
```

## 8. ⚠️ 当前不可用：有状态文档库路线

官方 skill 的主体建立在 `mineru` 这条**有状态**命令上（SQLite 文档库 + 缓存 + 后台服务）。在本便携整合包里，**这条路线目前有缺陷、不可用**，请绕开：

**受影响的功能**：`mineru server start|stop|status`、`mineru parse --json`、`mineru read`（按 locator 续读）、`mineru search`、`mineru find`、`mineru scan`、`mineru watch`、`mineru forget`、`mineru cleanup`、`mineru config`、`mineru show`、`mineru list`，以及一切依赖 `--json` 错误码 / `next_request` / `doc:{short_id}/...` locator 的流程。

**症状**：

- `mineru parse --json` 返回 `{"error":{"code":"server_not_running"}}`。
- `mineru server start` 看似能启动，但后台 worker 全部报
  `sqlite3.OperationalError: attempt to write a readonly database`，服务随后自行退出。
- 已排除的因素：文件权限、只读属性、文件系统、脏数据目录、SQLite 本身（改用全新目录、用外部进程直接写同一个库都能成功）——问题在服务进程内部，属**已知未修复缺陷**。

**因此，Agent 在本包里要这样做**：

- **不要**按官方 skill 的 locator / `--json` / `next_request` 工作流组织任务；
- 用 `mineru-kit parse` 的**产物文件**替代（§3）：正文读 `.md`，结构化读 `middle_json`，视觉证据看 `zip` 里的 `images/`；
- 需要反复调用就起 `mineru-kit api-server`（§4）；
- 用户报这个错时，如实说明是整合包的已知缺陷、有替代路径（`mineru-kit parse` / `api-server`），**不要**去改 MinerU 官方源码来"修"，那是本整合包的零改动红线。

## 9. 错误处理

| 现象 | 含义 | 动作 |
|---|---|---|
| 退出码 1 + `错误: 不支持的文件类型: <路径>` | 格式不受支持（如 `.txt`/`.md`） | 直接读源文件，**不要**重试解析 |
| 退出码 1 + `错误: <路径>` | 文件不存在或读不到 | 核对路径、确认文件可读 |
| 产出的 `.md` 体积异常大 | 文档含图，图片以 base64 内联了 | 改用 `-f zip`，读里面的 `markdown.md` |
| `No mapping for the Unicode character exists...` | 整合包路径含非 ASCII 字符 | 改用 `--tier basic`，或把整包移到纯英文路径（§5.4） |
| 显存/内存不足、进程被杀 | OOM | 降档（`standard`→`basic`）、用 `-p` 缩小页范围、分页多次解析 |
| `server_not_running` | 走了 doclib 路线 | 改用 `mineru-kit parse`（§8） |
| 输出目录里没有产物但退出码 0 | 大概是没解析到内容 | 用 `-v` 重跑一次看日志，确认输入路径与格式 |

重试规则：

- 只对明确可恢复的原因重试一次；不要对解析失败反复重试。
- **不要**在恢复过程中自行加 `--remote`——那要用户同意（§7）。
- 不要为了"把任务做完"就换一个非 MinerU 的解析器；先按上表处理，处理不了再如实报告。

## 10. 用结果回答用户

- 基于**实际解析出的内容**回答，不要凭对文档的猜测。
- **本包没有 doclib locator**，所以引用时用「文件名 + 页码」这种人类可读的方式，例如
  `《报告.pdf》第 7 页`。**不要**编造 `doc:xxxx/tier:standard/page:7` 形式的 locator——那在本包里取不到东西。
- 优先给简短摘录 + 页码，而不是大段复制原文。
- 内容被截断时说清"目前只读到第 N 页/第 M 块"。
- 需要断言尚未读到的部分时，先把那部分读出来。
- 表格、公式、图形、版面相关的问题，读对应页面，必要时看 `zip` 里的 `images/` 裁图。

## 11. 红线

- **不要修改 MinerU 官方源码**：`<KIT>/runtime/python/Lib/site-packages/mineru/**` 与 `.../docvortex/**` 一律只读。本整合包的约定是「官方源码零改动」，所有定制都在 `<KIT>/app/` 这层自写封装里。
- **不要往包内运行时 pip 安装任何东西**（会破坏可搬运性）。缺依赖让用户走菜单 `[5]`。
- 不要用 `<KIT>/runtime/python/Scripts/*.exe`。
- 未经同意不要上传文档（`--remote`）。
- 不要删用户的源文件；`-o` 只写输出目录。
- 不要把 `flash` 当作最终阅读质量。
- 不要把 base64 内联的图片数据大段贴进上下文。
- 不要把进度条 / `INFO` 日志当成结构化输出解析。
- 不要在没有可用档位时自作主张换掉 MinerU——先如实汇报，给用户选项。

## 附：术语与对应关系

| 说法 | 含义 |
|---|---|
| `<KIT>` | 整合包根目录，含 `启动MinerU.bat` |
| `启动MinerU.bat` | 人类用的交互入口：菜单 / 拖文件解析 |
| `app/cli.py` | 命令转发器，把官方命令名映射到包内模块（等价的 `app\bin\*.bat` 也走它） |
| `mineru-kit` | 无状态工具集：`parse` / `webui` / `api-server` / `vlm-server` / `router` / `models` / `version` |
| `mineru` | 有状态文档库命令，**本包当前不可用**（§8） |
| `data/models/.tier_choice` | 用户上次选定的档位偏好（一行） |
| `output/` | 包内约定的默认输出目录 |

官方命令的完整参数面，可用 `... mineru-kit parse --help` 等在包内直接查。
