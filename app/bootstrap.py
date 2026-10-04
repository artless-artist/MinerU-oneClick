"""首启自举：检查并自动补齐缺失的依赖与模型。

用途
    分享出去的「精简包」里不含 Python 依赖与模型权重（约 3 GB），
    用户第一次启动时由本模块按需下载；已经齐了的包（离线全量包）则几乎零开销跳过。

设计原则
    * 幂等：每次都先检查，齐了就静默跳过。
    * 只补缺的：不会覆盖已装好的依赖，也不会重下已有模型。
    * 国内优先：pip 走清华源、模型走 ModelScope；失败再回退官方源。
    * 可关闭：环境变量 MINERU_SKIP_SETUP=1（或在命令行加 --skip-setup）可整段跳过。
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import env_setup
import pkg_info
from pkg_info import LOCK_FILE, MINERU_VERSION, PYTHON_EXE, human

LINE = "=" * 66

# pip 源：先国内镜像，再官方。tuna 未收录的包用 --extra-index-url 兜底到 PyPI。
PIP_INDEXES: tuple[str, ...] = (
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple",
    "https://pypi.org/simple",
)
PIP_FALLBACK_EXTRA = "https://pypi.org/simple"


def skip_requested(argv: list[str] | None = None) -> bool:
    if os.environ.get("MINERU_SKIP_SETUP", "").strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return bool(argv and "--skip-setup" in argv)


def _run(cmd: list[str]) -> int:
    env = env_setup.build_env()
    try:
        return subprocess.call(cmd, env=env, cwd=str(env_setup.ROOT))
    except KeyboardInterrupt:
        print("\n  [已中断]")
        return 130


def _pip(args: list[str], index: str | None = None) -> int:
    cmd = [str(PYTHON_EXE), "-m", "pip", "install", "--no-input", "--no-warn-script-location"]
    if index:
        cmd += ["-i", index]
        if index != PIP_FALLBACK_EXTRA:
            cmd += ["--extra-index-url", PIP_FALLBACK_EXTRA]
    return _run(cmd + args)


# --------------------------------------------------------------------------
# 依赖
# --------------------------------------------------------------------------
def install_deps() -> bool:
    """安装/补齐 Python 依赖。优先按锁定表精确复现，失败再退回只装 mineru。"""
    print()
    print("  [1/2] 补齐 Python 依赖（首次约需 900 MB 下载，走国内镜像）")
    plans: list[tuple[list[str], str]] = []
    if LOCK_FILE.is_file():
        print(f"        使用版本锁定表 {LOCK_FILE.name}")
        plans.append((["-r", str(LOCK_FILE)], "锁定表"))
    # 包内若带了官方 wheel（分享时可选），优先用它，避免 PyPI 上的版本被撤回
    local_whl = sorted(env_setup.ROOT.glob("mineru-*.whl"))
    if local_whl:
        plans.append(([str(local_whl[-1])], f"包内 {local_whl[-1].name}"))
    plans.append(([f"mineru=={MINERU_VERSION}"], f"mineru=={MINERU_VERSION}"))

    # 先尽力更新 pip，老 pip 解析新轮子元数据可能出错
    for index in PIP_INDEXES:
        if _pip(["--upgrade", "pip", "--quiet"], index) == 0:
            break

    for args, label in plans:
        for index in PIP_INDEXES:
            print(f"        尝试 {label}  ← {index}")
            # 新装的包在同一个 site-packages 目录里，清一次导入缓存让 find_spec 立刻能看见
            importlib.invalidate_caches()
            if _pip(args, index) == 0 and pkg_info.deps_ready():
                print("        [完成] 依赖已就绪")
                return True
        print(f"        [失败] {label} 未能装全，换下一种方式")
    return False


# --------------------------------------------------------------------------
# 模型
# --------------------------------------------------------------------------
def install_models(tier: str = "standard") -> bool:
    """下载/补全模型（来源 ModelScope，与 MinerU 官方一致）。"""
    print()
    print(f"  [2/2] 下载模型权重（档位 {tier}，来源 ModelScope）")
    print("        basic    约 0.9 GB —— ONNX 小模型")
    if tier != "basic":
        print("        standard 再加约 1.2 GB —— 版面 VLM（GGUF）")
    print("        下载可中断，重跑本步骤会断点续传。")
    code = _run(
        [
            str(PYTHON_EXE),
            str(env_setup.ROOT / "app" / "cli.py"),
            "mineru-kit",
            "models",
            "download",
            "--tier",
            tier,
        ]
    )
    return code == 0 and pkg_info.models_ready_for(tier)


# --------------------------------------------------------------------------
# 总入口
# --------------------------------------------------------------------------
def ensure_ready(tier: str = "standard", argv: list[str] | None = None) -> bool:
    """检查运行环境，缺什么补什么。返回是否可以继续。"""
    if skip_requested(argv):
        return True

    missing = pkg_info.missing_modules()
    small, vlm = pkg_info.models_ready()
    need_models = not (small and vlm) if tier == "standard" else not small

    if not missing and not need_models:
        return True  # 常用路径：全量包/已补齐，直接放行

    print()
    print(LINE)
    print("  首次启动：正在检查运行环境")
    print(LINE)
    print(f"  程序目录 : {env_setup.ROOT}")
    print(f"  模型目录 : {env_setup.MODELS_DIR}")
    if missing:
        print(f"  Python 依赖 : 缺少 {len(missing)} 项 -> {', '.join(m for m, _ in missing)}")
    else:
        print("  Python 依赖 : 就绪")
    print(f"  模型权重 : 小模型 {'就绪' if small else '缺失'} / 版面 VLM {'就绪' if vlm else '缺失'}")
    print(LINE)
    print("  接下来会自动下载缺失部分，全程需要联网。")
    print("  想跳过请按 Ctrl+C，或用环境变量 MINERU_SKIP_SETUP=1 启动。")
    print()

    if missing and not install_deps():
        print()
        print(LINE)
        print("  [失败] Python 依赖未能装全。请检查网络后重试；")
        print("         或改用环境变量 MINERU_SKIP_SETUP=1 手动安装。")
        print(LINE)
        return False

    if need_models and not install_models(tier):
        print()
        print(LINE)
        print("  [失败] 模型未能下载完整。可稍后在菜单 [5] 重新下载。")
        print(LINE)
        return False

    print()
    print(LINE)
    print("  环境已就绪，继续启动。")
    print(LINE)
    return True


# --------------------------------------------------------------------------
# 命令行入口：python app\\bootstrap.py [--tier standard|basic]
# --------------------------------------------------------------------------
def main() -> int:
    env_setup.apply_env()
    env_setup.apply_safe_stdio()

    tier = "standard"
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--tier" and i + 1 < len(argv):
            tier = argv[i + 1]
    if "--basic" in argv:
        tier = "basic"

    # 直接用本模块时忽略 MINERU_SKIP_SETUP，尊重用户的显式调用
    os.environ.pop("MINERU_SKIP_SETUP", None)
    return 0 if ensure_ready(tier=tier) else 1


if __name__ == "__main__":
    raise SystemExit(main())
