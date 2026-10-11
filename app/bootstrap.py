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
import importlib.metadata
import json
import os
import platform
import re
import subprocess
import sys
from collections.abc import Callable
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
# 升级 MinerU（只替换上游程序包；模型、输出、设置都不动）
# --------------------------------------------------------------------------
# 为什么升级要额外做三件事，而不是「pip 装完就完事」：
#   自写层里有几处常量是**照着上游当时的样子写死**的 ——
#     * pkg_info.MINERU_VERSION —— 首启自举的兜底安装目标；
#     * requirements.lock.txt   —— bootstrap 的第一个安装计划，逐项钉死版本；
#   升级后若不同步这两处，下次「补齐依赖」会把刚升上去的版本**降级回旧版**。
#   另外新版可能换了模型仓库名/文件名，也要报出来（否则「模型明明在，启动器却
#   认为缺失」或反过来漏掉新文件）。
VERSION_PATTERN = re.compile(r"^\d+(\.\d+)*([._-]?(a|b|rc|dev|post)\d*)*$", re.IGNORECASE)

# 只把这些后缀当「权重文件」比对：上游 registry 里还登记了一堆 .yml 配置，
# 它们属下载随附项，不参与就绪判断，拿来做差异比对只会误报。
WEIGHT_SUFFIXES: tuple[str, ...] = (".onnx", ".gguf", ".pth", ".safetensors", ".bin")


def current_version() -> str | None:
    """当前实际装着的 mineru 版本。"""
    return pkg_info.mineru_version()


def is_version_like(text: str) -> bool:
    """粗略校验版本号写法，挡住「把路径当版本号输进去」这类误操作。"""
    return bool(VERSION_PATTERN.match(text.strip()))


def available_versions() -> tuple[str | None, list[str]]:
    """查询可安装的版本，返回 ``(最新版, 全部版本)``；查不到则 ``(None, [])``。"""
    for index in PIP_INDEXES:
        try:
            proc = subprocess.run(
                [str(PYTHON_EXE), "-m", "pip", "index", "versions", "mineru", "-i", index],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env_setup.build_env(),
                cwd=str(env_setup.ROOT),
                timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:  # noqa: BLE001
            continue
        latest: str | None = None
        versions: list[str] = []
        for line in f"{proc.stdout or ''}\n{proc.stderr or ''}".splitlines():
            line = line.strip()
            matched = re.match(r"^mineru \(([^)]+)\)", line)
            if matched:
                latest = matched.group(1).strip()
            if line.lower().startswith("available versions:"):
                versions = [v.strip() for v in line.split(":", 1)[1].split(",") if v.strip()]
        if latest or versions:
            return latest or versions[0], versions
    return None, []


def upgrade_mineru(target: str) -> bool:
    """把 mineru 升到 ``target``（依赖由 pip 一并处理），逐个镜像重试。"""
    before = pkg_info.mineru_version() or "(未安装)"
    print()
    print(f"  即将升级：mineru {before}  →  {target}")
    print("  只替换包内程序文件；模型权重、output 里的结果、个人设置都不受影响。")
    print()
    for index in PIP_INDEXES:
        print(f"        来源 {index}")
        code = _pip(["--upgrade", f"mineru=={target}"], index)
        installed = pkg_info.mineru_version()
        if code == 0 and installed == target:
            return True
        if code == 0:
            print(f"        [异常] 安装命令返回成功，但版本读出来是 {installed}，换下一个源重试")
        else:
            print(f"        [失败] 退出码 {code}，换下一个源重试")
    return False


def smoke_test() -> tuple[bool, list[str]]:
    """升级后冒烟测试：把 app/cli.py 里登记的每个命令入口都真的 import 一遍。

    这才是本次升级真正依赖的对外契约 —— 上游若改了模块路径，pip 不会报错，
    但菜单和命令行会当场失灵，所以宁可在这里花十几秒先撞出来。
    """
    import cli  # 同层模块：命令入口表以它为准，避免这里再抄一份

    modules = sorted({module for module, _attr in cli.COMMANDS.values()})
    script = (
        "import importlib, importlib.metadata as md\n"
        f"mods = {modules!r}\n"
        "bad = []\n"
        "for name in mods:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except BaseException as exc:\n"
        "        bad.append('%s -> %s: %s' % (name, type(exc).__name__, exc))\n"
        "print('SMOKE_VERSION ' + md.version('mineru'))\n"
        "for line in bad:\n"
        "    print('SMOKE_BAD ' + line)\n"
    )
    try:
        proc = subprocess.run(
            [str(PYTHON_EXE), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env_setup.build_env(),
            cwd=str(env_setup.ROOT),
            timeout=600,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as exc:  # noqa: BLE001
        return False, [f"冒烟测试无法启动：{type(exc).__name__}: {exc}"]

    notes: list[str] = []
    seen_version = False
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("SMOKE_VERSION"):
            seen_version = True
            notes.append("mineru 版本 = " + line.split(" ", 1)[-1])
        elif line.startswith("SMOKE_BAD"):
            notes.append("导入失败 " + line.split(" ", 1)[-1])
    if not seen_version:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
        notes.append("冒烟测试整体失败（退出码 %s）：%s" % (proc.returncode, " / ".join(tail)))
        return False, notes
    ok = not any(n.startswith("导入失败") for n in notes)
    return ok, notes


def _regenerate_lockfile(version: str) -> str | None:
    """按当前环境重新生成依赖锁定表；失败返回 ``None``。"""
    try:
        proc = subprocess.run(
            [str(PYTHON_EXE), "-m", "pip", "freeze"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env_setup.build_env(),
            cwd=str(env_setup.ROOT),
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return None
    if proc.returncode != 0:
        return None

    lines: list[str] = []
    rewritten = 0
    for raw in (proc.stdout or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if " @ " in line:
            # 用本地 wheel 装的包，pip freeze 会写成本机文件路径 —— 那玩意换台机器
            # 就装不上了，换回 ==版本号，锁定表才可移植。
            name = line.split(" @ ", 1)[0].strip()
            try:
                ver = importlib.metadata.version(name)
            except Exception:  # noqa: BLE001
                continue
            lines.append(f"{name}=={ver}")
            rewritten += 1
        else:
            lines.append(line)
    if not lines:
        return None

    header = (
        f"# MinerU {version} 便携包 —— 经验证的依赖版本锁定表\n"
        "#\n"
        "# 由包内 pip freeze 生成（菜单 [6] 升级 MinerU 时自动重新生成）。\n"
        f"# 生成环境：{platform.system()} {platform.machine()} / CPython {platform.python_version()}\n"
        "# 使用：runtime\\python\\python.exe -m pip install -r requirements.lock.txt\n"
        f"# 不想锁版本时可改用：pip install mineru=={version}\n"
    )
    try:
        LOCK_FILE.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        return None
    return f"依赖锁定表已重生成：{LOCK_FILE.name}（{len(lines)} 项" + (
        f"，其中 {rewritten} 项本地路径已改回版本号" if rewritten else ""
    ) + "）"


def sync_self_layer(new_version: str) -> list[str]:
    """升级后同步自写层「贴着上游版本写死」的两处，返回做了什么的说明。"""
    notes: list[str] = []
    old_version = pkg_info.MINERU_VERSION

    pkg_file = env_setup.ROOT / "app" / "pkg_info.py"
    try:
        text = pkg_file.read_text(encoding="utf-8")
    except OSError as exc:
        notes.append(f"[失败] 读不到 pkg_info.py：{exc}")
    else:
        old_line = f'MINERU_VERSION = "{old_version}"'
        if old_line in text:
            pkg_file.write_text(
                text.replace(old_line, f'MINERU_VERSION = "{new_version}"', 1), encoding="utf-8"
            )
            # bootstrap 用 `from pkg_info import MINERU_VERSION` 取的值副本，
            # 改完文件要同步本进程里的两处，否则横幅/兜底计划还说旧版本
            globals()["MINERU_VERSION"] = new_version
            pkg_info.MINERU_VERSION = new_version
            notes.append(f"MINERU_VERSION：{old_version} → {new_version}")
        else:
            notes.append(
                f"[注意] pkg_info.py 里没找到「MINERU_VERSION = \"{old_version}\"」这一行，"
                f"请手动改成 {new_version}"
            )

    if LOCK_FILE.is_file():
        result = _regenerate_lockfile(new_version)
        notes.append(result if result else "[注意] 依赖锁定表重新生成失败，建议删除 " + LOCK_FILE.name)
    else:
        notes.append(f"依赖锁定表不存在（{LOCK_FILE.name}），无需处理")
    return notes


def _weight_files(paths: list[str] | tuple[str, ...]) -> set[str]:
    return {p for p in paths if p.lower().endswith(WEIGHT_SUFFIXES)}


def upstream_model_catalog() -> dict | None:
    """问上游「这个版本期望哪些模型仓库与权重文件」（只读，不改任何东西）。"""
    script = (
        "import json\n"
        "from mineru.model.registry import small_model_repo, vlm_model_repo\n"
        "s = small_model_repo()\n"
        "v = vlm_model_repo()\n"
        "print('CATALOG ' + json.dumps({\n"
        "    'small': s.name, 'small_files': sorted(s.paths.values()),\n"
        "    'vlm': v.name, 'vlm_files': sorted(v.paths.values())}))\n"
    )
    try:
        proc = subprocess.run(
            [str(PYTHON_EXE), "-c", script],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env_setup.build_env(),
            cwd=str(env_setup.ROOT),
            timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception:  # noqa: BLE001
        return None
    for line in (proc.stdout or "").splitlines():
        if line.startswith("CATALOG "):
            try:
                return json.loads(line[len("CATALOG ") :])
            except json.JSONDecodeError:
                return None
    return None


def check_model_catalog() -> tuple[bool, list[str]]:
    """比对「新版期望的模型」与「pkg_info.py 登记的清单」，返回 (是否一致, 说明)。"""
    catalog = upstream_model_catalog()
    if catalog is None:
        return True, ["[跳过] 读不到新版期望的模型清单（不影响使用，模型状态请看菜单 [4]）"]

    issues: list[str] = []
    small_name = catalog.get("small") or ""
    vlm_name = catalog.get("vlm") or ""
    if small_name and small_name != pkg_info.SMALL_MODEL_DIR.name:
        issues.append(f"小模型目录名变了：新版期望 {small_name}，本包含 {pkg_info.SMALL_MODEL_DIR.name}")
    if vlm_name and vlm_name != pkg_info.VLM_MODEL_DIR.name:
        issues.append(f"版面 VLM 目录名变了：新版期望 {vlm_name}，本包含 {pkg_info.VLM_MODEL_DIR.name}")

    expected_small = _weight_files(catalog.get("small_files") or [])
    expected_vlm = _weight_files(catalog.get("vlm_files") or [])
    added_small = expected_small - set(pkg_info.SMALL_MODEL_FILES)
    added_vlm = expected_vlm - set(pkg_info.VLM_MODEL_FILES)
    if added_small:
        issues.append("新版新增了小模型权重：" + "、".join(sorted(added_small)))
    if added_vlm:
        issues.append("新版新增了 VLM 权重：" + "、".join(sorted(added_vlm)))

    # 反向：本包登记、新版已不认（说明该文件被淘汰了）
    known_small = set(catalog.get("small_files") or [])
    known_vlm = set(catalog.get("vlm_files") or [])
    stale = (set(pkg_info.SMALL_MODEL_FILES) - known_small) | (set(pkg_info.VLM_MODEL_FILES) - known_vlm)
    if stale:
        issues.append("本包登记但新版已不认（可清理）" + "、".join(sorted(stale)))

    if issues:
        return False, issues
    return True, [
        f"模型清单与上游一致：{pkg_info.SMALL_MODEL_DIR.name}（小模型）、"
        f"{pkg_info.VLM_MODEL_DIR.name}（VLM），无需重下"
    ]


# --------------------------------------------------------------------------
# 总入口
# --------------------------------------------------------------------------
def ensure_ready(
    tier: str = "standard",
    argv: list[str] | None = None,
    *,
    tier_chooser: Callable[[], str] | None = None,
    ask_if_missing: bool = True,
) -> bool:
    """检查运行环境，缺什么补什么。返回是否可以继续。

    行为（按优先级）：

    1. 使用者**已选定过档位**（``data/models/.tier_choice``）：直接按该档位
       检查、缺什么补什么，**不再询问**。缺件且补不上时只给一次提示。
    2. **从没选过**、且当前档位确实缺件：调用 ``tier_chooser`` 让使用者选，
       然后按选择补齐。选择会被记住，以后启动不再重复问。
    3. 一切齐备（全量包 / 已补齐）：零开销直接放行，一句不问。

    ``ask_if_missing=False`` 用于无人交互的场景（拖文件直接解析），此时不询问。
    """
    if skip_requested(argv):
        return True

    missing = pkg_info.missing_modules()
    small, vlm = pkg_info.models_ready()

    # 已表达过偏好：以它为准，不再拿「模型齐不齐」去打扰使用者。
    chosen, was_partial = pkg_info.read_tier_choice()
    if chosen is not None:
        tier = chosen

    ready_now = not missing and pkg_info.models_ready_for(tier)
    if ready_now:
        return True  # 常用路径：全量包 / 已补齐 / basic 用户，零开销跳过

    # 从没选过 + 真的缺件 -> 问一次，并记住。必须在打印环境报告、开始下载之前。
    # 说明：这里用「当前档位够不够用」（models_ready_for）而不是「模型全不全」，
    # 这样 basic 用户（小模型在、VLM 故意不装）不会再被反复询问。
    if chosen is None and tier_chooser is not None and ask_if_missing:
        selected = tier_chooser()
        if selected in ("standard", "basic"):
            tier = selected
        pkg_info.write_tier_choice(tier)

    need_models = not pkg_info.models_ready_for(tier)

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
    print(f"  本次档位 : {tier}" + ("" if need_models else "（已就绪，无需下载）"))
    print(LINE)
    if need_models:
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

    # 与 launcher 一致：所有 print 走「按窗口宽度安全折行」（见 uikit 注释）。
    # 经由 launcher 调用时它已经装过了，这里重复装一次只是让本模块单独运行也生效。
    import uikit

    uikit.install()

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
