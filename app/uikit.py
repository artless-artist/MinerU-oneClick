"""控制台输出的一个保险 —— 按窗口宽度安全折行。

为什么需要
    Windows 控制台有一条很少被注意到的规则：**某一行的显示宽度正好等于窗口
    列数时，它会多做一次换行**。真控制台实测（chcp 65001，见 _tmp/probe3）：

        67 列窗口：`  提示：选 basic 可省下约 1.2 GB；以后想升级，菜单 [5] 可随时补下。`
                   （正好 67 格）之后凭空多出一个空行，后面的提示符被挤低一行
        68 列窗口：同一屏、同一份代码，没有那个空行

    首启档位菜单里正好占满整行的行不止一条 —— 显示宽度分别是
    52 / 63 / 66 / 67 / 71 列（提示符行是 26）。也就是说：**只要使用者把窗口
    调成这几个列数中的一个，整屏就会凭空多出空行、后面每一行整体漂一格**。
    这属于「行列整体错一格」这类怪现象的来源之一；顺带它还让窄窗口下的
    控制台把汉字从中间劈开。

怎么办
    主动折行：任何一行都折到 `width - 1` 列以内，就永远碰不到那条规则。
    折行优先在空格处断、否则按字符边界断（不会把一个汉字劈成两半）。

代价
    窗口 ≥ 72 列时，菜单最长的一行是 71 列，`wrap_line` 原样返回 ——
    输出与改造前**逐字节相同**。只有窄窗口才生效。
"""

from __future__ import annotations

import shutil
import sys
import unicodedata

__all__ = ["console_width", "display_width", "wrap_line", "out", "install"]

# 不能落在行首的标点（简单禁则）：折行时若标点正好要开头，把前一个字一起挪下去
NO_START = "。，、；：？！）】》」』”’…—"


def console_width(default: int = 120) -> int:
    """当前控制台/终端的列数；拿不到就按 120 算（cmd 的默认值）。"""
    try:
        cols = shutil.get_terminal_size().columns
    except Exception:  # noqa: BLE001
        cols = 0
    return max(20, cols or default)


def display_width(text: str) -> int:
    """字符串占多少显示列（CJK 全角算 2 列）。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in text)


def wrap_line(text: str, width: int) -> list[str]:
    """把一行折成不超过 ``width - 1`` 列的若干行。

    按字符边界断（不会把汉字劈成两半），并做最简禁则：不让 。，、）等标点
    孤零零地落在下一行行首。
    """
    limit = max(8, width - 1)
    if display_width(text) <= limit:
        return [text]
    # 分隔线这类「同一个字符重复一整行」的，直接截到 width-1，别折成两条
    if len(set(text)) == 1 and text.isascii() and len(text) > limit:
        return [text[:limit]]
    chunks: list[str] = []
    cur = ""
    cur_w = 0
    for ch in text:
        ch_w = 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
        if cur_w + ch_w > limit:
            tail = ""
            if ch in NO_START and len(cur) >= 2:
                tail = cur[-1]          # 禁则：标点前那个字跟着下去
                cur = cur[:-1]
                cur_w = display_width(cur)
            chunks.append(cur.rstrip())
            cur, cur_w = tail, display_width(tail) if tail else 0
        cur += ch
        cur_w += ch_w
    if cur:
        chunks.append(cur.rstrip())
    return chunks


def out(*args, sep: str = " ", end: str = "\n", file=None, flush: bool = False) -> None:
    """``print`` 的安全版：逐行折到 width-1 列以内再写出去。"""
    stream = file if file is not None else sys.stdout
    text = sep.join(str(a) for a in args) + end
    trailing = text.endswith("\n")
    body = text[:-1] if trailing else text
    width = console_width()
    lines: list[str] = []
    for line in body.split("\n"):
        lines.extend(wrap_line(line, width))
    stream.write("\n".join(lines) + ("\n" if trailing else ""))
    if flush:
        stream.flush()


def install() -> None:
    """把 ``out`` 装到 ``builtins.print`` 上：本进程内所有 print 都走安全折行。

    只替换 ``print``，不动 ``sys.stdout`` —— 子进程直通控制台的输出、
    ``input()`` 的提示符写入都不受影响。
    """
    import builtins

    builtins.print = out  # type: ignore[assignment]
