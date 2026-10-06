"""便携包的「资产清单」—— 一个整合包跑起来需要哪些东西、现在齐了没有。

单一真相来源：launcher.py（自检/横幅）与 bootstrap.py（首启自动补齐）都从这里取判断，
避免两边各写一份清单、改了一处忘了另一处。

清单口径与 mineru/model/registry.py 保持一致；模型文件缺一不可，且必须带
上游的完成标记文件（.mineru_complete），否则 MinerU 仍会判定「未就绪」去重下。
"""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
from pathlib import Path

from env_setup import MODELS_DIR, PYTHON_DIR, ROOT

# --------------------------------------------------------------------------
# 模型资产
# --------------------------------------------------------------------------
SMALL_MODEL_DIR = MODELS_DIR / "MinerU-4_models_onnx"
VLM_MODEL_DIR = MODELS_DIR / "MinerU2.5-Pro-2605-1.2B-GGUF"

SMALL_MODEL_FILES = (
    "Layout/PP-DocLayoutV2/inference.onnx",
    "MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.onnx",
    "OCR/paddleocr/ch_PP-OCRv6_tiny_det_infer.onnx",
    "OCR/paddleocr/ch_PP-OCRv6_small_rec_infer.onnx",
    "OCR/paddleocr/seal_PP-OCRv4_det_infer.onnx",
    "Table/slanet-plus.onnx",
    "Table/unet.onnx",
    "Table/PP-LCNet_x1_0_table_cls.onnx",
)
VLM_MODEL_FILES = (
    "MinerU2.5-Pro-2605-1.2B-Q8_0.gguf",
    "mmproj-MinerU2.5-Pro-2605-1.2B-Q8_0.gguf",
)

# --------------------------------------------------------------------------
# Python 依赖资产
# --------------------------------------------------------------------------
# 导入名 -> 说明。只列「缺了就跑不起来」的关键项；其余由 pip 依赖解析保证。
REQUIRED_MODULES: tuple[tuple[str, str], ...] = (
    ("mineru", "MinerU 本体"),
    ("onnxruntime", "ONNX 小模型推理"),
    ("mineru_llama_cpp", "llama.cpp 版面 VLM"),
    ("gradio", "网页界面"),
    ("cv2", "图像处理"),
    ("docvortex", "文档解析内核"),
)

MINERU_VERSION = "4.0.10"
LOCK_FILE = ROOT / "requirements.lock.txt"
PYTHON_EXE = PYTHON_DIR / "python.exe"
LLAMA_SERVER = PYTHON_DIR / "Lib" / "site-packages" / "mineru_llama_cpp" / "bin" / "llama-server.exe"


# --------------------------------------------------------------------------
# 体积辅助
# --------------------------------------------------------------------------
def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                pass
    return total


# --------------------------------------------------------------------------
# 就绪判断
# --------------------------------------------------------------------------
def missing_files(base: Path, names: tuple[str, ...]) -> list[str]:
    return [n for n in names if not (base / n).is_file()]


def models_ready() -> tuple[bool, bool]:
    """返回 (小模型就绪, 版面 VLM 就绪)。"""
    small = SMALL_MODEL_DIR.is_dir() and not missing_files(SMALL_MODEL_DIR, SMALL_MODEL_FILES)
    vlm = (
        VLM_MODEL_DIR.is_dir()
        and not missing_files(VLM_MODEL_DIR, VLM_MODEL_FILES)
        and (VLM_MODEL_DIR / ".mineru_complete").is_file()
    )
    return small, vlm


def models_ready_for(tier: str) -> bool:
    """按档位判断是否够用：basic 只要有 ONNX 小模型，standard 两者都要。"""
    small, vlm = models_ready()
    return small if tier == "basic" else (small and vlm)


# --------------------------------------------------------------------------
# 档位偏好（记住使用者选过什么）
# --------------------------------------------------------------------------
# 为什么需要这个文件：
#   「模型齐不齐」与「使用者想用哪一档」是两件事。只想用 basic 的人，常态就是
#   「小模型在、VLM 故意不装」——如果拿「模型不齐」当询问条件，他每次启动都会
#   被问一遍「要不要下 VLM」。所以把偏好单独记下来，询问时机改为
#   「从没选过 + 当前档位真的缺东西」。
#
# 放在 models 目录下（与 VLM 的 .mineru_complete 同一层），随模型一起被整体
# 拷贝/清理；文件极小，只有一行档位名。
TIER_CHOICE_FILE = MODELS_DIR / ".tier_choice"
PARTIAL_MARKER = ".partial"  # 与档位名同文件：basic.partial 表示「借用 basic 跑，缺 VLM」


def _parse_tier_choice(text: str) -> tuple[str | None, bool]:
    """解析标记文件内容 -> (档位, 是否为「容忍缺件」状态)。"""
    lines = [ln.strip().lower() for ln in (text or "").splitlines() if ln.strip()]
    if not lines:
        return None, False
    raw = lines[0]
    partial = len(lines) > 1 and lines[1] == PARTIAL_MARKER.lstrip(".")
    tier = raw if raw in ("basic", "standard") else None
    return tier, partial


def read_tier_choice() -> tuple[str | None, bool]:
    """读取使用者上次选定的档位。

    返回 ``(tier, partial)``：

    * ``tier`` 为 ``"basic"`` / ``"standard"``；从没选过则为 ``None``。
    * ``partial=True`` 表示上次是「明知缺件也照样用」——例如选了 standard 但
      VLM 没下成，或者选了 basic 后想留个念想。此时重新启动只做静默提示，
      不再反复追问。
    """
    try:
        return _parse_tier_choice(TIER_CHOICE_FILE.read_text(encoding="utf-8"))
    except OSError:
        return None, False


def write_tier_choice(tier: str, *, partial: bool = False) -> None:
    """落盘使用者选定的档位（失败不抛异常，只是下次会重新问一次）。"""
    if tier not in ("basic", "standard"):
        return
    body = tier if not partial else f"{tier}\n{PARTIAL_MARKER}"
    try:
        TIER_CHOICE_FILE.parent.mkdir(parents=True, exist_ok=True)
        TIER_CHOICE_FILE.write_text(body + "\n", encoding="utf-8")
    except OSError:
        pass


def missing_modules() -> list[tuple[str, str]]:
    """返回 [(导入名, 说明), ...]，仅含真正导入不了的。"""
    missing: list[tuple[str, str]] = []
    for mod, label in REQUIRED_MODULES:
        try:
            found = importlib.util.find_spec(mod) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append((mod, label))
    return missing


def deps_ready() -> bool:
    return not missing_modules()


def mineru_version() -> str | None:
    try:
        return importlib.metadata.version("mineru")
    except Exception:  # noqa: BLE001
        return None


def everything_ready() -> bool:
    return deps_ready() and models_ready_for("standard")


def status_line() -> str:
    """一行摘要，给横幅用。"""
    if everything_ready():
        return "完整（依赖 + 全部模型就绪）"
    bits: list[str] = []
    missing = missing_modules()
    if missing:
        bits.append(f"缺依赖 {len(missing)} 个（{missing[0][0]} 等）")
    small, vlm = models_ready()
    if not small:
        bits.append("缺 ONNX 小模型")
    elif not vlm:
        bits.append("缺版面 VLM")
    return "需补齐：" + "，".join(bits) if bits else "完整"
