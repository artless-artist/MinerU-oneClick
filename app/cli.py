"""命令行转发器 —— 让 pip 安装出来的 MinerU 命令在便携包里稳定可用。

为什么不用 ``runtime/python/Scripts/*.exe``：pip 生成的命令行外壳会把安装时的
*python.exe 绝对路径* 写进自身，整包换个盘符/目录后就会失效。这里改为显式调用
包内解释器 + 模块入口，天然可搬移。

用法（等同于官方命令）::

    python app\\cli.py mineru-kit parse in.pdf -o out.md --tier standard
    python app\\cli.py mineru-models-download --tier standard
    python app\\cli.py --list
"""

from __future__ import annotations

import importlib
import sys

import env_setup

# 命令名 -> (模块, 可调用对象)。与 wheel 的 entry_points.txt 一一对应。
COMMANDS: dict[str, tuple[str, str]] = {
    "mineru": ("mineru.cli.main", "main"),
    "mineru-kit": ("mineru.kit.main", "main"),
    "mineru-api": ("mineru.kit.commands.api_server", "main"),
    "mineru-models-download": ("mineru.kit.commands.models", "download_main"),
    "mineru-openai-server": ("mineru.kit.commands.vlm_server", "main"),
    "mineru-router": ("mineru.kit.router.cli", "main"),
    "mineru-webui": ("mineru.kit.commands.webui", "main"),
}


def _print_commands() -> None:
    print("可用命令：")
    for name in COMMANDS:
        print(f"  {name}")


def _warn_if_vlm_unavailable(name: str, args: list[str]) -> None:
    """命令行直接调用时，也把「中文路径 + VLM 档位」的问题讲清楚。

    否则用户只会看到原生库抛出的
    ``RuntimeError: No mapping for the Unicode character exists ...``，
    完全看不出是路径引起的。
    """
    if env_setup.path_is_ascii():
        return
    if name not in ("mineru-kit", "mineru") or "parse" not in args:
        return
    tier = "standard"
    if "--tier" in args:
        index = args.index("--tier")
        if index + 1 < len(args):
            tier = args[index + 1]
    if tier in env_setup.VLM_TIERS:
        print(
            "[警告] 本包路径含非英文字符，档位 "
            f"'{tier}' 需要的版面 VLM 无法加载（原生库不支持非 ASCII 模型路径）。\n"
            "        建议改用 --tier basic；或把整个文件夹移到纯英文路径后重试。",
            file=sys.stderr,
        )


def main() -> int:
    env_setup.apply_env()

    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "--list", "list"):
        _print_commands()
        return 0

    name, rest = argv[0], argv[1:]
    target = COMMANDS.get(name)
    if target is None:
        print(f"[错误] 未知命令：{name}", file=sys.stderr)
        _print_commands()
        return 2

    _warn_if_vlm_unavailable(name, rest)

    module_name, attr = target
    module = importlib.import_module(module_name)
    # Typer/Click 从 sys.argv 取参数，这里还原成官方入口看到的样子
    sys.argv = [name, *rest]
    result = getattr(module, attr)()
    return result if isinstance(result, int) else 0


if __name__ == "__main__":
    sys.exit(main())
