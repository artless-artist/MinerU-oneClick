"""MinerU 便携包的环境隔离。

单点定义所有环境变量，保证：

* 一切可变路径都落在包内（模型、日志、临时文件、缓存、索引库），
  ``MINERU_HOME`` 指向 ``<包根>/data``，所以整包拷到任何位置都能直接用；
* 不读取宿主机的 PYTHONPATH / PYTHONHOME / 用户 site-packages，
  也不会往宿主机的 %TEMP%、%APPDATA% 写文件；
* 模型源固定为 ModelScope（本包已预置模型，仅作兜底）。

无论是 ``launcher.py``（菜单）、``cli.py``（命令行转发）还是 ``app/bin`` 下的
批处理外壳，都从这里取环境，避免多处定义漂移。
"""

from __future__ import annotations

import os
import socket
import sys
from pathlib import Path

# 包根目录（本文件位于 <包根>/app/ 下）
ROOT: Path = Path(__file__).resolve().parent.parent
PYTHON_DIR: Path = ROOT / "runtime" / "python"
PYTHON_EXE: Path = PYTHON_DIR / "python.exe"
DATA_DIR: Path = ROOT / "data"
MODELS_DIR: Path = DATA_DIR / "models"
OUTPUT_DIR: Path = ROOT / "output"

# 包内需要存在的可写目录：(相对 data 的路径, 用途)
DATA_SUBDIRS: tuple[tuple[str, str], ...] = (
    ("temp", "临时文件（TEMP/TMP）"),
    ("logs", "MinerU 运行日志"),
    ("models", "模型权重"),
    ("hf-cache", "HuggingFace 缓存"),
    ("ms-cache", "ModelScope 缓存"),
    ("gradio", "WebUI 临时产物"),
    ("appdata", "隔离的 %APPDATA%"),
    ("localappdata", "隔离的 %LOCALAPPDATA%"),
    # Intel/NVIDIA 驱动的 shader 缓存会写到 %LOCALAPPDATA% 的兄弟目录 LocalLow，
    # 我们重定向了 LOCALAPPDATA，所以它也会落在包内（体积很小）。
    ("LocalLow", "GPU 驱动 shader 缓存"),
)


# 依赖版面 VLM（llama.cpp）的档位；这些档位要求「模型文件能被原生库以窄字符路径打开」，
# 而 llama.cpp 的 Windows 构建做不到这点 —— 只要包路径含非 ASCII 字符就会在
# Engine 构造阶段抛 RuntimeError: No mapping for the Unicode character exists in the
# target multi-byte code page.（已实测：中文路径必现，ASCII + 空格正常。）
VLM_TIERS: tuple[str, ...] = ("flash", "standard", "advanced")


def path_is_ascii() -> bool:
    """整包路径（含盘符、各级目录名）是否全部为 ASCII 字符。"""
    return str(ROOT).isascii()


def vlm_path_blocker() -> str | None:
    """包路径不可用于 VLM 档位时返回说明文本；可用则返回 None。"""
    if path_is_ascii():
        return None
    return (
        "整包路径含有非英文字符，standard / advanced / flash 档位（版面 VLM）"
        "在本机无法加载模型。\n"
        f"    当前路径：{ROOT}\n"
        "    解决办法：把这个 MinerU 文件夹整体移动到全部由英文、数字、"
        "下划线、连字符和空格组成的路径下（例如 D:\\Tools\\MinerU），再启动。\n"
        "    basic 档不受影响，中文路径下可以正常使用。"
    )


def ensure_dirs() -> None:
    """确保包内所有可写目录存在（拷贝到新机器后也自愈）。"""
    for name, _desc in DATA_SUBDIRS:
        (DATA_DIR / name).mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def build_env() -> dict[str, str]:
    """返回用于启动 MinerU 子进程的完整环境变量。"""
    ensure_dirs()
    env = os.environ.copy()

    # 顺序即优先级，app/bin 必须排在 Scripts 前面：
    # pip 生成的 Scripts\*.exe 把安装时的 python.exe 绝对路径写进了自身，
    # 整包换目录后就会失效；app/bin 下的外壳走的是相对路径，搬移后依然可用。
    path_parts = [str(ROOT / "app" / "bin"), str(PYTHON_DIR), str(PYTHON_DIR / "Scripts")]
    env["PATH"] = os.pathsep.join(path_parts + [env.get("PATH", "")])

    env.update(
        {
            # ---- MinerU 自身 ----
            "MINERU_HOME": str(DATA_DIR),
            "MINERU_MODEL_SOURCE": "modelscope",
            "MINERU_LANG": "zh",
            # ---- Python 运行时 ----
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONNOUSERSITE": "1",  # 不加载宿主机用户 site-packages
            "PYTHONDONTWRITEBYTECODE": "1",  # 不在包内生成新的 __pycache__
            # ---- 零足迹：临时目录与缓存全部包内化 ----
            "TEMP": str(DATA_DIR / "temp"),
            "TMP": str(DATA_DIR / "temp"),
            "HF_HOME": str(DATA_DIR / "hf-cache"),
            "HUGGINGFACE_HUB_CACHE": str(DATA_DIR / "hf-cache" / "hub"),
            "MODELSCOPE_CACHE": str(DATA_DIR / "ms-cache"),
            "GRADIO_TEMP_DIR": str(DATA_DIR / "gradio"),
            "APPDATA": str(DATA_DIR / "appdata"),
            "LOCALAPPDATA": str(DATA_DIR / "localappdata"),
            # ---- 关闭遥测 ----
            "GRADIO_ANALYTICS_ENABLED": "False",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "MODELSCOPE_TELEMETRY": "off",
            "DO_NOT_TRACK": "1",
        }
    )

    # 宿主机注入的这些变量会污染便携解释器，必须清掉
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP"):
        env.pop(key, None)
    return env


def apply_env() -> dict[str, str]:
    """写入当前进程并返回环境副本（供 import mineru 之前调用）。"""
    env = build_env()
    os.environ.update(env)
    return env


def apply_safe_stdio() -> None:
    """控制台按 UTF-8 输出中文，避免 GBK 乱码/报错。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except Exception:  # noqa: BLE001
            pass


def find_free_port(start: int = 7860, limit: int = 60) -> int:
    """从 start 起找一个空闲的本机端口。"""
    for port in range(start, start + limit):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    return start
