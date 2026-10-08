"""MinerU 4.0.10 便携版 —— 一键启动菜单。

所有中文提示都在这里打印（启动用的 .bat 保持纯 ASCII，避免 cmd.exe 按
GBK 解析 UTF-8 时吞掉换行导致的诡异报错）。

「缺什么、齐了没」的判断统一取自 pkg_info，首启自动补齐交给 bootstrap，
本文件只负责交互与展示。
"""

from __future__ import annotations

import importlib.metadata
import os
import subprocess
import sys
from pathlib import Path

import bootstrap
import env_setup
import pkg_info
from env_setup import DATA_DIR, MODELS_DIR, OUTPUT_DIR, PYTHON_EXE, ROOT
from pkg_info import (
    LLAMA_SERVER,
    REQUIRED_MODULES,
    SMALL_MODEL_DIR,
    SMALL_MODEL_FILES,
    VLM_MODEL_DIR,
    VLM_MODEL_FILES,
    dir_size,
    human,
    missing_files,
    missing_modules,
    models_ready,
    models_ready_for,
)

LINE = "=" * 66


# --------------------------------------------------------------------------
# 工具
# --------------------------------------------------------------------------
def vulkan_devices() -> list[str]:
    """探测版面 VLM（llama.cpp）可用的 Vulkan 设备。

    直接问包内的 llama-server --list-devices，得到的就是真正会被使用的设备，
    比查注册表或读驱动信息可靠。探测失败/无设备时返回空列表（此时 VLM 会自动
    回落到 CPU，功能不受影响，只是慢）。
    """
    if not LLAMA_SERVER.is_file():
        return []
    try:
        proc = subprocess.run(
            [str(LLAMA_SERVER), "--list-devices"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return []
    out = f"{proc.stdout or ''}\n{proc.stderr or ''}"
    return [line.strip() for line in out.splitlines() if line.strip().startswith("Vulkan")]


def run_mineru(args: list[str], *, cwd: Path | None = None) -> int:
    """以包内解释器运行 ``mineru app.cli`` 命令，输出直通当前控制台。"""
    env = env_setup.build_env()
    cmd = [str(PYTHON_EXE), str(ROOT / "app" / "cli.py"), *args]
    print()
    try:
        return subprocess.call(cmd, env=env, cwd=str(cwd or ROOT))
    except KeyboardInterrupt:
        print("\n[已中断]")
        return 130


def pause(msg: str = "按回车键返回菜单…") -> None:
    try:
        input(f"\n{msg}")
    except (EOFError, KeyboardInterrupt):
        print()


def ask(prompt: str, default: str = "") -> str:
    try:
        raw = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return default
    return raw or default


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


# --------------------------------------------------------------------------
# 横幅
# --------------------------------------------------------------------------
def banner() -> None:
    small, vlm = models_ready()
    chosen, _partial = pkg_info.read_tier_choice()
    print()
    print(LINE)
    print("  MinerU 4.0.10  便携版   ——  PDF / 图片 / Office 文档  →  Markdown")
    print(LINE)
    print(f"  程序目录 : {ROOT}")
    print(f"  模型目录 : {MODELS_DIR}")
    print(f"  输出目录 : {OUTPUT_DIR}")
    status_small = "就绪" if small else "缺失"
    status_vlm = "就绪" if vlm else "缺失"
    total = dir_size(MODELS_DIR)
    deps_bad = len(missing_modules())
    deps_state = "就绪" if deps_bad == 0 else f"缺失 {deps_bad} 项"
    print(f"  Python 依赖 : {deps_state}")
    print(f"  模型状态 : 小模型 {status_small} / 版面 VLM {status_vlm}   (共 {human(total)})")
    if chosen is not None:
        print(f"  档位偏好 : {chosen}（决定补下哪些模型、命令行向导的默认值；")
        print("               WebUI 内可随时切换档位，不受此项限制）")
    # 只有「当前档位真的不够用」才提示补齐 —— basic 用户不用看 VLM 缺失的告警
    active = chosen or ("standard" if env_setup.path_is_ascii() else "basic")
    if deps_bad or not models_ready_for(active):
        print("  [提示] 组件不完整：菜单 [4] 可查看缺什么，[5] 可自动补齐")
    if not env_setup.path_is_ascii():
        print(LINE)
        print("  [重要] 本包所在路径含非英文字符，standard / advanced / flash 档")
        print("         无法调用版面 VLM（会报“No mapping for the Unicode character”）。")
        print("         请把整个文件夹移到纯英文路径（如 D:\\Tools\\MinerU）后使用；")
        print("         或先改用 basic 档（中文路径下可正常工作）。")
    print(LINE)


def ask_tier(*, first_run: bool = False, default: str = "standard") -> str:
    """询问解析档位，返回 "standard" / "basic"。

    只在需要时调用（首次下载模型、或进入 WebUI / 解析向导）。
    ``first_run=True`` 时用「下载量」口径提示，其余场景用「识别质量」口径。
    ``default`` 是回车时的取值：优先沿用使用者上次选过的档位。
    """
    print()
    if first_run:
        print("  请选择要下载的模型档位（现在选，之后才开始下载）：")
        print("    [1] standard  小模型 + 版面 VLM   约 2.1 GB  （推荐，识别质量最好）")
        print("                  公式、表格、多栏排版更准")
        print("    [2] basic     仅小模型            约 0.9 GB  （快、省空间）")
        print("                  纯文本 PDF 效果接近；复杂排版 / 公式可能识别不佳")
        print()
        print("  提示：选 basic 可省下约 1.2 GB；以后想升级，菜单 [5] 可随时补下。")
    else:
        print("  解析档位（影响识别质量与速度）：")
        print("    [1] standard  推荐。ONNX 小模型 + 版面 VLM，识别质量最好")
        print("                  公式、表格、多栏排版更准；较慢、占显存较多")
        print("    [2] basic     只用 ONNX 小模型。快、省显存，纯文本 PDF 效果接近")
        print("                  无版面 VLM，复杂排版 / 公式可能识别不佳")
    hint = "1" if default != "basic" else "2"
    picked = ask(f"  请选择 [1/2]（回车={hint}）：", hint)
    return {"1": "standard", "2": "basic"}.get(picked, default)


def remembered_tier() -> str:
    """使用者上次选定的档位；从没选过则返回按路径推出的默认值。"""
    chosen, _partial = pkg_info.read_tier_choice()
    if chosen is not None:
        return chosen
    return "standard" if env_setup.path_is_ascii() else "basic"


def webui_server_tier() -> str:
    """WebUI 该对外广告到哪一档 —— 由「本机实际装了什么」决定，而不是去问使用者。

    为什么这里不能问：WebUI 界面里本身就有一个档位滑块，它的候选项来自
    服务端广告出来的能力（`mineru-kit webui --api-server-tier`，
    上游 `TIERS_BY_SERVER_TIER`）：

        --api-server-tier standard -> flash / basic / standard / advanced
        --api-server-tier basic    -> flash / basic

    启动前再问一遍，除了多余，还会把界面里的选项从 4 个砍成 2 个 ——
    明明装全了模型的人，反而在界面里找不到 standard / advanced。
    所以这里只判断「最高能跑到哪」，把选择权交回界面。
    """
    small, vlm = models_ready()
    if small and vlm and env_setup.path_is_ascii():
        return "standard"
    return "basic"


def resolve_tier(tier: str, *, where: str) -> str:
    """按档位把模型备齐；缺什么补什么，全部就绪时静默通过。

    返回最终实际使用的档位（中文路径下 VLM 档会被自动降回 basic）。
    """
    blocker = env_setup.vlm_path_blocker()
    if tier in env_setup.VLM_TIERS and blocker is not None:
        print()
        print("  [冲突] 所选档位需要版面 VLM，但它无法在非英文路径下加载：")
        print(f"    {blocker}")
        print()
        print("  已自动改用 basic 档继续（纯文本 PDF 效果差不多）。")
        print(f"  如确实要 standard：先把文件夹移到纯英文路径，再重跑{where}。")
        tier = "basic"
        pkg_info.write_tier_choice(tier)

    if missing_modules() or not models_ready_for(tier):
        print()
        print(f"  所选档位（{tier}）组件还没齐，先补齐再继续。")
        if not bootstrap.ensure_ready(tier=tier, argv=["--tier", tier], ask_if_missing=False):
            print()
            print("  [失败] 组件未能补齐，请检查网络后重试；")
            print("         或改用菜单 [5] 手动补齐。")
            pause()
            return tier
    return tier


def menu() -> None:
    print()
    print("  [1] 打开网页界面 (WebUI)      ← 推荐，拖拽文件即可解析")
    print("  [2] 解析文件（命令行向导）")
    print("  [3] 打开 MinerU 命令行")
    print("  [4] 环境自检 / 模型校验")
    print("  [5] 检查并补齐缺失组件（依赖 + 模型）")
    print("  [0] 退出")
    print()


# --------------------------------------------------------------------------
# [1] WebUI
# --------------------------------------------------------------------------
def action_webui() -> None:
    port = env_setup.find_free_port(7860)
    url = f"http://127.0.0.1:{port}"

    # 不再询问档位：界面里本来就有档位选择器，这里只把「本机能跑的最高档」透传过去。
    tier = webui_server_tier()
    if missing_modules() or not models_ready_for(tier):
        print()
        print(f"  补齐 {tier} 档所需组件…")
        if not bootstrap.ensure_ready(tier=tier, argv=["--tier", tier], ask_if_missing=False):
            print()
            print("  [失败] 组件未能补齐，请检查网络后重试；")
            print("         或改用菜单 [5] 手动补齐。")
            pause()
            return

    print()
    print(LINE)
    print("  即将启动网页界面，浏览器会自动打开：")
    print(f"      {url}")
    print("  首次解析需要加载模型，可能要等几十秒。")
    print("  关闭时：回到本窗口按 Ctrl+C，或直接关掉本窗口。")
    if tier == "standard":
        print("  档位在界面内切换：flash / basic / standard / advanced")
    else:
        print("  档位在界面内切换：flash / basic")
        if not env_setup.path_is_ascii():
            print("  （本包路径含非英文字符，版面 VLM 无法加载，故只开放这两档；")
            print("    移到纯英文路径后即可解锁 standard / advanced）")
        else:
            print("  （本机只装了 ONNX 小模型；菜单 [5] 可补下版面 VLM，")
            print("    之后就能在界面里选 standard / advanced）")
    print(LINE)
    print()
    run_mineru(
        [
            "mineru-kit",
            "webui",
            "--server-name",
            "127.0.0.1",
            "--server-port",
            str(port),
            "--output-dir",
            str(OUTPUT_DIR),
            "--api-server-tier",
            tier,
        ]
    )
    pause()


# --------------------------------------------------------------------------
# [2] 解析向导
# --------------------------------------------------------------------------
def action_parse(argv: list[str] | None = None) -> None:
    print()
    print("  支持格式：PDF、png/jpg 等图片、doc/docx、ppt/pptx、xls/xlsx、")
    print("            epub、ofd、html、csv、rtf、odt/ods/odp、mhtml")
    print("  可以直接把文件从资源管理器拖进本窗口，或粘贴完整路径；")
    print("  多个文件/整个文件夹用空格分隔。")
    print()

    if argv:
        raw = " ".join(argv)
        print(f"  已接收参数：{raw}")
    else:
        raw = ask("  请输入文件或文件夹路径：")

    if not raw.strip():
        print("  [取消] 没有输入路径。")
        pause()
        return

    inputs: list[Path] = []
    for token in raw.replace('"', " ").replace("'", " ").split():
        path = Path(strip_quotes(token)).expanduser()
        if not path.exists():
            print(f"  [警告] 路径不存在，已跳过：{path}")
            continue
        inputs.append(path)
    if not inputs:
        print("  [取消] 没有有效路径。")
        pause()
        return

    print()
    tier = ask_tier(default=remembered_tier())
    pkg_info.write_tier_choice(tier)
    tier = resolve_tier(tier, where="本向导")

    print()
    print("  输出格式：")
    print("    [1] markdown     单文件 .md。图片以 base64 内联在正文里（默认）")
    print("                     体积大，适合只取文字、或整篇丢给 AI 读")
    print("    [2] zip          推荐。得到 markdown.md + images/ 图片文件，")
    print("                     正文用 images/xxx.jpg 相对路径引用，便于存档")
    print("    [3] middle_json  结构化 JSON，不含图片，适合二次开发")
    # 序号与名称都接受，避免习惯直接敲 markdown / zip 的人被静默改成默认值
    fmt_raw = ask("  请选择 [1/2/3]（回车=1）：", "1")
    fmt = {"1": "markdown", "2": "zip", "3": "middle_json"}.get(fmt_raw, fmt_raw)
    if fmt not in ("markdown", "middle_json", "zip"):
        fmt = "markdown"

    args = ["mineru-kit", "parse", *[str(p) for p in inputs], "-o", str(OUTPUT_DIR), "--tier", tier, "-f", fmt]
    print()
    print(f"  输出目录：{OUTPUT_DIR}")
    print(f"  执行：mineru-kit parse ... --tier {tier} -f {fmt}")
    code = run_mineru(args)
    if code == 0:
        print()
        print(f"  [完成] 结果已写入：{OUTPUT_DIR}")
    else:
        print()
        print(f"  [失败] 退出码 {code}，请查看上方日志（日志目录：{DATA_DIR / 'logs'}）")
    pause()


# --------------------------------------------------------------------------
# [3] 交互式命令行
# --------------------------------------------------------------------------
def action_shell() -> None:
    print()
    print("  已进入 MinerU 命令行（PATH 里已有 mineru / mineru-kit 等命令）。")
    print("  常用示例：")
    print("    mineru-kit parse 文档.pdf -o D:\\out\\文档.md --tier standard")
    print("    mineru-kit models verify --tier standard")
    print("    mineru-kit --help")
    print("  输入 exit 返回菜单。")
    print()
    env = env_setup.build_env()
    comspec = env.get("COMSPEC") or r"C:\Windows\System32\cmd.exe"
    try:
        subprocess.call([comspec, "/k"], env=env, cwd=str(ROOT))
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------
# [4] 自检
# --------------------------------------------------------------------------
def action_selfcheck() -> None:
    print()
    print(LINE)
    print("  环境自检")
    print(LINE)

    print(f"[1] 便携解释器   : {PYTHON_EXE}")
    print(f"                  存在={PYTHON_EXE.is_file()}  版本={sys.version.split()[0]}")

    try:
        ver = importlib.metadata.version("mineru")
        print(f"[2] mineru 版本   : {ver}")
    except Exception as exc:  # noqa: BLE001
        print(f"[2] mineru 版本   : 读取失败 ({exc})")

    print("[3] 关键依赖      :")
    for mod, label in REQUIRED_MODULES:
        try:
            __import__(mod)
            state = "OK"
        except Exception as exc:  # noqa: BLE001
            state = f"失败 ({type(exc).__name__}: {exc})"
        print(f"      {label:<18} {mod:<18} {state}")

    small, vlm = models_ready()
    print("[4] 模型          :")
    print(f"      小模型 (basic 档)  : {'就绪' if small else '缺失'}  {SMALL_MODEL_DIR}")
    for name in missing_files(SMALL_MODEL_DIR, SMALL_MODEL_FILES):
        print(f"          缺少 {name}")
    print(f"      版面 VLM (standard): {'就绪' if vlm else '缺失'}  {VLM_MODEL_DIR}")
    for name in missing_files(VLM_MODEL_DIR, VLM_MODEL_FILES):
        print(f"          缺少 {name}")
    if VLM_MODEL_DIR.is_dir() and not (VLM_MODEL_DIR / ".mineru_complete").is_file():
        print("          缺少 .mineru_complete 标记（会被判定为未就绪）")
    print(f"      模型总体积        : {human(dir_size(MODELS_DIR))}")

    print("[5] 路径隔离      :")
    for key in ("MINERU_HOME", "TEMP", "APPDATA", "LOCALAPPDATA", "HF_HOME", "MODELSCOPE_CACHE"):
        value = os.environ.get(key, "(未设置)")
        inside = "包内 OK" if value != "(未设置)" and value.lower().startswith(str(ROOT).lower()) else "包外 !"
        print(f"      {key:<16} = {value}   [{inside}]")

    print("[6] 路径字符集    :")
    if env_setup.path_is_ascii():
        print(f"      纯 ASCII        : 是  -> standard 档可用")
    else:
        print(f"      纯 ASCII        : 否  -> 版面 VLM 不可用（只能 basic 档）")
        print(f"      {env_setup.vlm_path_blocker()}")

    print("[7] 硬件与加速    :")
    print(f"      CPU 逻辑核数      : {os.cpu_count()}")
    print(f"      MINERU_DEVICE_MODE: {os.environ.get('MINERU_DEVICE_MODE', '(未设置 → 自动)')}")
    devices = vulkan_devices()
    if devices:
        print("      版面 VLM 加速后端  : Vulkan（会自动挑选显卡，无需配置）")
        for dev in devices:
            print(f"          {dev}")
    else:
        print("      版面 VLM 加速后端  : 未检测到可用 Vulkan 设备")
        print("          -> 自动回落到 CPU，功能不受影响，只是慢一些")
    try:
        import onnxruntime

        providers = onnxruntime.get_available_providers()
        print(f"      ONNX 可用后端     : {providers}")
        if not any(tag in p for p in providers for tag in ("CUDA", "TensorRT", "Dml", "OpenVINO")):
            print("          -> 版面分析/OCR/公式识别固定跑 CPU（本包设计如此）")
    except Exception as exc:  # noqa: BLE001
        print(f"      ONNX 后端探测失败 : {exc}")

    print()
    print("[8] 用 MinerU 官方命令复核模型状态：")
    run_mineru(["mineru-kit", "models", "verify", "--tier", "standard"])

    print()
    print(LINE)
    print("  自检结束")
    print(LINE)
    pause()


# --------------------------------------------------------------------------
# [5] 下载模型
# --------------------------------------------------------------------------
def action_download_models() -> None:
    print()
    print("  检查依赖与模型，缺失的部分自动补齐。")
    print("  依赖走清华 PyPI 镜像；模型走 ModelScope（与 MinerU 官方一致）。")
    print("  basic 档需要 ONNX 小模型（约 860 MB）；")
    print("  standard 档还需要版面 VLM（约 1.24 GB）。")
    print()
    tier = ask_tier(default=remembered_tier())
    pkg_info.write_tier_choice(tier)

    missing = missing_modules()
    if missing:
        print()
        print(f"  缺少 {len(missing)} 个依赖：{', '.join(m for m, _ in missing)}")
        if not bootstrap.install_deps():
            print("\n  [失败] 依赖未装全，请检查网络后重试。")
            pause()
            return
    if not models_ready_for(tier):
        if not bootstrap.install_models(tier):
            print("\n  [失败] 模型未下载完整，请检查网络后重试。")
            pause()
            return
    print()
    print("  [完成] 组件已就绪。")
    pause()


# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def main() -> int:
    env_setup.apply_env()
    env_setup.apply_safe_stdio()

    argv = sys.argv[1:]
    # 首启自举：缺依赖/模型就自动下载（全量包或已补齐时几乎零开销直接放行）。
    # 档位取「使用者上次选过的」；从没选过才在下载前问一次，且只问这一次。
    # 拖文件直接解析（argv 传了路径）时无人交互，不询问，直接用默认/记住的档位：
    # 中文路径下 standard 本来就不可用，此时只下 basic，省掉 1.2 GB。
    headless = bool(argv) and all(not a.startswith("-") for a in argv)
    default_tier = "standard" if env_setup.path_is_ascii() else "basic"

    def _choose() -> str:
        picked = ask_tier(first_run=True, default=default_tier)
        pkg_info.write_tier_choice(picked)
        return picked

    if not bootstrap.ensure_ready(
        tier=default_tier,
        argv=argv,
        tier_chooser=_choose,
        ask_if_missing=not headless,
    ):
        pause("  按回车键退出…")
        return 1

    # 支持「把文件拖到 启动MinerU.bat 上」直接解析
    if headless:
        banner()
        action_parse(argv)
        return 0

    while True:
        os.system("cls")
        banner()
        menu()
        choice = ask("  请选择 [0-5]（回车=1）：", "1")
        os.system("cls")

        if choice in ("1", "webui"):
            banner()
            action_webui()
        elif choice in ("2", "parse"):
            banner()
            action_parse()
        elif choice in ("3", "shell", "cli"):
            banner()
            action_shell()
        elif choice in ("4", "check"):
            action_selfcheck()
        elif choice in ("5", "models", "download"):
            banner()
            action_download_models()
        elif choice in ("0", "q", "quit", "exit"):
            print("\n  已退出。\n")
            return 0
        else:
            print(f"\n  [提示] 无效选择：{choice}")
            pause()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n  已中断退出。\n")
        sys.exit(130)
