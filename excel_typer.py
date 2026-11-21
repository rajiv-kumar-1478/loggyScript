"""
Excel Typer — Human-Like Spreadsheet Replication
=================================================
Reads tabular data from a CSV, TSV, JSON, or Excel file and re-types
it cell-by-cell into Microsoft Excel (or any spreadsheet application),
simulating authentic human-like typing biometrics and keyboard navigation.

Key Excel-Specific Features:
  1. Grid Navigation:
     - Natural `Tab` across columns, `Enter` at row end (standard Excel rhythm)
     - Optional arrow-based navigation mode (`--nav-mode arrows`)
     - In-cell line breaks typed with `Alt+Enter` (instead of breaking the cell)
     - Settle latency modeling (realistic delay for Excel to commit cell edits)
  2. OS-Level Input via Windows SendInput:
     - Zero external dependencies (pure ctypes, no pynput required)
     - Hardware scan codes for physical keyboard fidelity
     - Realistic key dwell times (press -> hold -> release)
     - Shift synchronization with human pre-delay
  3. Window & Focus Guard:
     - Pins typing to Microsoft Excel window (`--target-window "Excel"`)
     - Elevation / UAC mismatch detection
     - Refuses to type or pauses if Excel loses focus (prevents keystroke spray)
  4. Human Biometrics:
     - Digraph difficulty (fast vs slow letter/number transitions)
     - Finger & hand alternation difficulty models
     - Typo engine (substitution, doubling, transposition, omission + backspacing)
     - Fatigue accumulation, warm-up phase, rhythm drift, cognitive pauses
     - Natural mouse micro-movements and grid glancing
  5. State Persistence & Safety:
     - Progress tracked in `excel_typer_progress.json`
     - Auto-save workbook (`Ctrl+S`) every N rows (`--save-interval`)
     - Resumable from any row (`--resume` or `--start-row`)
     - Automatic rest breaks after prolonged typing sessions

Usage:
  # 1. Type a CSV file into Excel
  python excel_typer.py --file "C:\\data\\sales.csv"

  # 2. Preview rows and estimated time without typing
  python excel_typer.py --file "C:\\data\\sales.csv" --dry-run

  # 3. Type at 1.5x speed with auto-save every 5 rows
  python excel_typer.py --file "C:\\data\\sales.csv" --speed 1.5 --save-interval 5

  # 4. Resume from row 12 after interruption
  python excel_typer.py --file "C:\\data\\sales.csv" --resume

  # 5. Type built-in sample inventory sheet (no file needed)
  python excel_typer.py --sample

WARNING: Educational & research simulation tool.
"""

import os
import sys
import time
import random
import math
import argparse
import threading
import subprocess
import json
import csv
from datetime import datetime

# ──────────────────────────────────────────────
#  OS-Level Windows API via ctypes (SendInput)
# ──────────────────────────────────────────────
import ctypes
import ctypes.wintypes

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_advapi32 = ctypes.windll.advapi32

_user32.GetForegroundWindow.restype = ctypes.wintypes.HWND
_user32.GetForegroundWindow.argtypes = []
_user32.IsWindow.restype = ctypes.wintypes.BOOL
_user32.IsWindow.argtypes = [ctypes.wintypes.HWND]
_user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
_user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]
_user32.IsIconic.restype = ctypes.wintypes.BOOL
_user32.IsIconic.argtypes = [ctypes.wintypes.HWND]
_user32.GetWindowTextLengthW.restype = ctypes.c_int
_user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]
_user32.GetWindowTextW.restype = ctypes.c_int
_user32.GetWindowTextW.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int
]
_user32.GetClassNameW.restype = ctypes.c_int
_user32.GetClassNameW.argtypes = [
    ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.c_int
]
_user32.SetForegroundWindow.restype = ctypes.wintypes.BOOL
_user32.SetForegroundWindow.argtypes = [ctypes.wintypes.HWND]
_user32.BringWindowToTop.restype = ctypes.wintypes.BOOL
_user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]
_user32.SetFocus.restype = ctypes.wintypes.HWND
_user32.SetFocus.argtypes = [ctypes.wintypes.HWND]
_user32.ShowWindow.restype = ctypes.wintypes.BOOL
_user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.c_int]
_user32.AttachThreadInput.restype = ctypes.wintypes.BOOL
_user32.AttachThreadInput.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.DWORD, ctypes.wintypes.BOOL
]
_user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
_user32.GetWindowThreadProcessId.argtypes = [
    ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)
]
_kernel32.OpenProcess.restype = ctypes.wintypes.HANDLE
_kernel32.OpenProcess.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.BOOL, ctypes.wintypes.DWORD
]
_kernel32.CloseHandle.restype = ctypes.wintypes.BOOL
_kernel32.CloseHandle.argtypes = [ctypes.wintypes.HANDLE]
_kernel32.GetConsoleWindow.restype = ctypes.wintypes.HWND
_kernel32.GetConsoleWindow.argtypes = []
_advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.HANDLE)
]
_advapi32.GetTokenInformation.restype = ctypes.wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


def _send_mouse_input(dx: int, dy: int, mouse_data: int = 0, flags: int = MOUSEEVENTF_MOVE):
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(
        dx=dx, dy=dy, mouseData=mouse_data,
        dwFlags=flags, time=0,
        dwExtraInfo=ctypes.pointer(extra)
    )
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _get_cursor_pos() -> tuple:
    point = ctypes.wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _get_screen_size() -> tuple:
    w = _user32.GetSystemMetrics(0)
    h = _user32.GetSystemMetrics(1)
    return w, h


# ──────────────────────────────────────────────
#  Hardware Scan Codes (PS/2 Set 1)
# ──────────────────────────────────────────────
VK_TO_SCAN = {
    # Letters
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C,
    # Numbers
    '0': 0x0B, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09, '9': 0x0A,
    # Symbols (unshifted)
    '-': 0x0C, '=': 0x0D, '[': 0x1A, ']': 0x1B, '\\': 0x2B,
    ';': 0x27, "'": 0x28, '`': 0x29, ',': 0x33, '.': 0x34,
    '/': 0x35, ' ': 0x39,
    # Navigation / Control keys
    'enter': 0x1C, 'tab': 0x0F, 'backspace': 0x0E,
    'lshift': 0x2A, 'rshift': 0x36, 'lctrl': 0x1D,
    'lalt': 0x38, 'capslock': 0x3A, 'escape': 0x01,
    'delete': 0x53, 'home': 0x47, 'end': 0x4F,
    'pageup': 0x49, 'pagedown': 0x51,
    'up': 0x48, 'down': 0x50, 'left': 0x4B, 'right': 0x4D,
    'f1': 0x3B, 'f2': 0x3C, 'f3': 0x3D, 'f4': 0x3E,
    'f5': 0x3F, 'f6': 0x40, 'f7': 0x41, 'f8': 0x42,
    'f9': 0x43, 'f10': 0x44, 'f11': 0x57, 'f12': 0x58,
}

SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
    ':': ';', '"': "'", '~': '`', '<': ',', '>': '.',
    '?': '/',
}


def _os_key_press(scan_code: int):
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(
        wVk=0, wScan=scan_code,
        dwFlags=KEYEVENTF_SCANCODE,
        time=0, dwExtraInfo=ctypes.pointer(extra)
    )
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _os_key_release(scan_code: int):
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(
        wVk=0, wScan=scan_code,
        dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
        time=0, dwExtraInfo=ctypes.pointer(extra)
    )
    _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _os_type_unicode(char: str):
    extra = ctypes.c_ulong(0)
    for c in char:
        code = ord(c)
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(
            wVk=0, wScan=code,
            dwFlags=KEYEVENTF_UNICODE,
            time=0, dwExtraInfo=ctypes.pointer(extra)
        )
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))

        inp2 = INPUT()
        inp2.type = INPUT_KEYBOARD
        inp2.union.ki = KEYBDINPUT(
            wVk=0, wScan=code,
            dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
            time=0, dwExtraInfo=ctypes.pointer(extra)
        )
        _user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))


def _os_type_char_with_dwell(char: str, dwell_time: float = None):
    if dwell_time is None:
        dwell_time = random.lognormvariate(math.log(0.085), 0.3)
        dwell_time = max(0.04, min(dwell_time, 0.25))

    needs_shift = False
    base_char = char

    if char in SHIFT_MAP:
        needs_shift = True
        base_char = SHIFT_MAP[char]
    elif char.isupper():
        needs_shift = True
        base_char = char.lower()

    scan = VK_TO_SCAN.get(base_char)
    if scan is None:
        _os_type_unicode(char)
        return

    shift_scan = VK_TO_SCAN['lshift']

    if needs_shift:
        _os_key_press(shift_scan)
        time.sleep(random.uniform(0.015, 0.04))

    _os_key_press(scan)
    time.sleep(dwell_time)
    _os_key_release(scan)

    if needs_shift:
        time.sleep(random.uniform(0.01, 0.03))
        _os_key_release(shift_scan)


def _os_press_special(key_name: str, dwell_time: float = None):
    if dwell_time is None:
        dwell_time = random.uniform(0.05, 0.12)
    scan = VK_TO_SCAN.get(key_name)
    if scan is None:
        return
    _os_key_press(scan)
    time.sleep(dwell_time)
    _os_key_release(scan)


def _os_hotkey(modifier: str, key_char: str):
    """Executes a hotkey with authentic modifier hold and release timings."""
    mod_scan = VK_TO_SCAN.get(modifier)
    key_scan = VK_TO_SCAN.get(key_char)
    if not mod_scan or not key_scan:
        return
    _os_key_press(mod_scan)
    time.sleep(random.uniform(0.03, 0.07))
    _os_key_press(key_scan)
    time.sleep(random.uniform(0.05, 0.10))
    _os_key_release(key_scan)
    time.sleep(random.uniform(0.02, 0.05))
    _os_key_release(mod_scan)


# ──────────────────────────────────────────────
#  Window Discovery & Focus Guard
# ──────────────────────────────────────────────

def _safe_text(text: str) -> str:
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors='replace').decode(encoding, errors='replace')


def _window_title(hwnd) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ''
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_class(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_pid(hwnd) -> int:
    pid = ctypes.wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_thread_id(hwnd) -> int:
    pid = ctypes.wintypes.DWORD()
    return _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))


def _get_foreground_window():
    return _user32.GetForegroundWindow()


def _list_windows() -> list:
    windows = []

    @WNDENUMPROC
    def _collect(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            title = _window_title(hwnd)
            if title:
                windows.append({
                    'hwnd': hwnd,
                    'title': title,
                    'class': _window_class(hwnd),
                    'pid': _window_pid(hwnd),
                })
        return True

    _user32.EnumWindows(_collect, 0)
    return windows


def is_excel_window(w: dict, pattern: str = None, exact: bool = False) -> bool:
    """
    Checks if a window is genuinely Microsoft Excel (class XLMAIN)
    and strictly excludes the command prompt, terminal, PowerShell, and self.
    """
    hwnd = w.get('hwnd')
    try:
        console_hwnd = _kernel32.GetConsoleWindow()
        if console_hwnd and hwnd == console_hwnd:
            return False
    except Exception:
        pass

    if w.get('pid') == os.getpid():
        return False

    cls = w.get('class', '')
    if cls in ('ConsoleWindowClass', 'CASCADIA_HOSTING_WINDOW_CLASS', 'PseudoConsoleWindow', 'CabinetWClass'):
        return False

    title = w.get('title', '').strip()
    title_lower = title.lower()

    if 'excel_typer' in title_lower or 'cmd.exe' in title_lower or 'powershell' in title_lower:
        return False

    # Microsoft Excel main window class is 'XLMAIN'
    if cls == 'XLMAIN':
        if not pattern or pattern.casefold() == 'excel':
            return True
        stem = os.path.splitext(pattern)[0].casefold()
        if stem in title_lower or pattern.casefold() in title_lower:
            return True
        return False

    # Fallback title match for Calc or virtualized Office wrappers
    if pattern:
        if exact:
            return title == pattern
        return pattern.casefold() in title_lower
    return title_lower.endswith(' - excel') or title_lower == 'excel'


def find_windows(pattern: str, exact: bool = False) -> list:
    if not pattern:
        return []
    if 'excel' in pattern.casefold():
        return [w for w in _list_windows() if is_excel_window(w, pattern=pattern, exact=exact)]

    res = []
    needle = pattern.casefold()
    for w in _list_windows():
        if not is_excel_window(w, pattern=pattern, exact=exact):
            continue
        res.append(w)
    return res


def _focus_window(hwnd) -> bool:
    if not _user32.IsWindow(hwnd):
        return False
    if _user32.IsIconic(hwnd):
        _user32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.25)
    if _user32.GetForegroundWindow() == hwnd:
        return True

    fg = _user32.GetForegroundWindow()
    fg_tid = _window_thread_id(fg) if fg else 0
    tgt_tid = _window_thread_id(hwnd)
    attached = False
    try:
        if fg_tid and tgt_tid and fg_tid != tgt_tid:
            attached = bool(_user32.AttachThreadInput(fg_tid, tgt_tid, True))
        _user32.BringWindowToTop(hwnd)
        _user32.SetForegroundWindow(hwnd)
        _user32.SetFocus(hwnd)
    finally:
        if attached:
            _user32.AttachThreadInput(fg_tid, tgt_tid, False)

    return _user32.GetForegroundWindow() == hwnd


def _is_process_elevated(pid: int) -> bool:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        token = ctypes.wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(handle, TOKEN_QUERY, ctypes.byref(token)):
            return False
        try:
            elevation = ctypes.wintypes.DWORD()
            size = ctypes.wintypes.DWORD()
            if not _advapi32.GetTokenInformation(
                token, TokenElevation,
                ctypes.byref(elevation), ctypes.sizeof(elevation),
                ctypes.byref(size)
            ):
                return False
            return bool(elevation.value)
        finally:
            _kernel32.CloseHandle(token)
    finally:
        _kernel32.CloseHandle(handle)


def _is_self_elevated() -> bool:
    return _is_process_elevated(os.getpid())


class WindowGuard:
    """Locks the typer to the target spreadsheet window and guards against focus loss."""

    def __init__(self, pattern: str = "Excel", exact: bool = False, refocus: bool = True):
        self.pattern = pattern
        self.exact = exact
        self.refocus = refocus
        self.hwnd = None
        self.title = ''
        self.pid = 0
        self.refocus_events = 0

    def resolve(self) -> bool:
        matches = find_windows(self.pattern, exact=self.exact)
        if not matches:
            print(f"\n  [FOCUS] No visible window matches --target-window {self.pattern!r}")
            self._print_candidates()
            return False

        if len(matches) > 1:
            fg = _get_foreground_window()
            chosen = next((w for w in matches if w['hwnd'] == fg), matches[0])
            print(f"\n  [FOCUS] {len(matches)} windows match {self.pattern!r} — selecting:")
            for w in matches:
                mark = '→' if w['hwnd'] == chosen['hwnd'] else ' '
                print(f"    {mark} {_safe_text(w['title'])}")
        else:
            chosen = matches[0]

        self.hwnd = chosen['hwnd']
        self.title = chosen['title']
        self.pid = chosen['pid']

        if not _user32.IsWindow(self.hwnd):
            print(f"  [FOCUS] Target spreadsheet window closed before typing.")
            return False

        print(f"  [FOCUS] Locked onto: {_safe_text(self.title)}")
        print(f"          class={chosen['class']}  pid={self.pid}")

        if _is_process_elevated(self.pid) and not _is_self_elevated():
            print("\n  [FOCUS] ERROR: Target spreadsheet runs elevated (admin) but this script does not.")
            print("          Windows blocks SendInput from a normal process to an elevated window.")
            print("          Fix: Run this script as Administrator, or launch Excel normally.")
            return False

        return True

    def _print_candidates(self):
        candidates = [w for w in _list_windows() if w['title'].strip()]
        if not candidates:
            return
        print("          Visible windows right now:")
        for w in candidates[:15]:
            print(f"            - {_safe_text(w['title'])}")
        if len(candidates) > 15:
            print(f"            ... and {len(candidates) - 15} more")

    def alive(self) -> bool:
        return self.hwnd is not None and bool(_user32.IsWindow(self.hwnd))

    def ensure_focus(self, attempts: int = 1, stop_event: threading.Event = None) -> bool:
        if not self.alive():
            print("  [FOCUS] Target spreadsheet window was closed.")
            return False
        if _get_foreground_window() == self.hwnd:
            return True
        if not self.refocus:
            return True

        # When the user switches away to another window, immediately pause
        # and wait cleanly until they switch back to Excel.
        return self.pause_until_focused(stop_event)

    def pause_until_focused(self, stop_event: threading.Event = None) -> bool:
        """
        Gracefully pauses when Excel loses focus, and automatically resumes
        the moment the user clicks or switches back to Excel!
        """
        if not self.alive():
            return False

        if _get_foreground_window() == self.hwnd:
            return True

        if not self.refocus:
            return True

        self.refocus_events += 1
        print(f"\n{'⏸ '*18}")
        print(f"  [PAUSED] Window changed — Excel lost focus.")
        print(f"  Typing is paused safely. Switch back to Excel to auto-resume...")
        print(f"{'⏸ '*18}\n")

        # Wait loop until user switches back to Excel
        while _get_foreground_window() != self.hwnd:
            if stop_event and stop_event.is_set():
                return False
            if not self.alive():
                print(f"  [Excel] Excel window was closed.")
                return False
            time.sleep(0.4)

        print(f"\n{'▶ '*18}")
        print(f"  [RESUMED] Excel is focused! Continuing typing in 1 second...")
        print(f"{'▶ '*18}\n")
        time.sleep(1.0)
        return True

    def check(self) -> bool:
        return self.pause_until_focused()

    def summary(self) -> str:
        if self.hwnd is None:
            return "no target window"
        return f"{_safe_text(self.title)!r} ({self.refocus_events} refocus events)"


# ──────────────────────────────────────────────
#  Human Mouse Simulation (OS-level via SendInput)
# ──────────────────────────────────────────────

class HumanMouseSimulator:
    """Simulates realistic subtle hand micro-movements across an Excel sheet."""

    def __init__(self):
        self.screen_w, self.screen_h = _get_screen_size()

    def _bezier_point(self, t: float, p0, p1, p2, p3) -> tuple:
        u = 1 - t
        x = (u**3 * p0[0] + 3 * u**2 * t * p1[0] +
             3 * u * t**2 * p2[0] + t**3 * p3[0])
        y = (u**3 * p0[1] + 3 * u**2 * t * p1[1] +
             3 * u * t**2 * p2[1] + t**3 * p3[1])
        return int(x), int(y)

    def _generate_control_points(self, start, end) -> tuple:
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = math.sqrt(dx**2 + dy**2)
        offset = dist * random.uniform(0.1, 0.35)
        angle = math.atan2(dy, dx) + random.choice([-1, 1]) * random.uniform(0.3, 0.8)
        c1 = (int(start[0] + dist * 0.3 * math.cos(angle)),
              int(start[1] + dist * 0.3 * math.sin(angle)))
        c2 = (int(end[0] - dist * 0.3 * math.cos(angle)),
              int(end[1] - dist * 0.3 * math.sin(angle)))
        return c1, c2

    def move_to(self, target_x: int, target_y: int, steps: int = None,
                duration: float = None):
        start_x, start_y = _get_cursor_pos()
        dx = target_x - start_x
        dy = target_y - start_y
        dist = math.sqrt(dx**2 + dy**2)
        if dist < 5:
            return

        if steps is None:
            steps = max(10, min(int(dist / 12), 40))
        if duration is None:
            duration = max(0.08, min(dist / 1400.0, 0.5))

        step_delay = duration / steps
        c1, c2 = self._generate_control_points((start_x, start_y), (target_x, target_y))

        for i in range(1, steps + 1):
            t = i / float(steps)
            t_eased = t * t * (3.0 - 2.0 * t)  # Smooth step
            bx, by = self._bezier_point(t_eased, (start_x, start_y), c1, c2, (target_x, target_y))

            tremor_x = random.randint(-1, 1) if random.random() < 0.25 else 0
            tremor_y = random.randint(-1, 1) if random.random() < 0.25 else 0
            abs_x = int((bx + tremor_x) * 65535 / self.screen_w)
            abs_y = int((by + tremor_y) * 65535 / self.screen_h)

            _send_mouse_input(abs_x, abs_y, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE)
            time.sleep(step_delay * random.uniform(0.8, 1.2))

    def idle_drift(self):
        cx, cy = _get_cursor_pos()
        dx = random.randint(-8, 8)
        dy = random.randint(-6, 6)
        tx = max(10, min(cx + dx, self.screen_w - 10))
        ty = max(10, min(cy + dy, self.screen_h - 10))
        self.move_to(tx, ty, steps=random.randint(6, 12), duration=random.uniform(0.1, 0.25))


# ──────────────────────────────────────────────
#  Human Motor Model Constants
# ──────────────────────────────────────────────
KEY_FINGER = {
    'q': 0, 'a': 0, 'z': 0, '1': 0,
    'w': 1, 's': 1, 'x': 1, '2': 1,
    'e': 2, 'd': 2, 'c': 2, '3': 2,
    'r': 3, 'f': 3, 'v': 3, 't': 3, 'g': 3, 'b': 3, '4': 3, '5': 3,
    'y': 4, 'h': 4, 'n': 4, 'u': 4, 'j': 4, 'm': 4, '6': 4, '7': 4,
    'i': 5, 'k': 5, ',': 5, '8': 5,
    'o': 6, 'l': 6, '.': 6, '9': 6,
    'p': 7, ';': 7, '/': 7, '0': 7, '-': 7, '=': 7,
    '[': 7, ']': 7, "'": 7, '\\': 7, '`': 7,
}

KEY_DIFFICULTY = {
    'q': 1.25, 'z': 1.30, 'p': 1.15, 'x': 1.12,
    '/': 1.20, ';': 1.10, "'": 1.10, '-': 1.10,
    '=': 1.10, ',': 1.05, '.': 1.05,
}

KEY_DWELL_BIAS = {
    'q': 1.20, 'z': 1.25, 'p': 1.12, 'x': 1.10,
    '/': 1.15, ';': 1.08, "'": 1.08, '-': 1.06,
    '=': 1.06,
}


# ──────────────────────────────────────────────
#  Excel Typing Profile
# ──────────────────────────────────────────────

class ExcelTypingProfile:
    """Configures biometric human-like delays, mistakes, and Excel navigation."""

    def __init__(self, speed_multiplier: float = 1.0):
        self.speed_multiplier = max(0.1, speed_multiplier)

        # Base keystroke delay (seconds)
        self.base_delay_min = 0.04 / self.speed_multiplier
        self.base_delay_max = 0.13 / self.speed_multiplier

        # Dwell time (how long key stays pressed)
        self.dwell_mean = 0.085
        self.dwell_sigma = 0.30

        # Excel cell navigation & commit settle times
        # Humans wait for the cell border to shift and Excel to commit before typing
        self.cell_settle_delay = (0.09 / self.speed_multiplier, 0.22 / self.speed_multiplier)
        self.empty_cell_glance = (0.05 / self.speed_multiplier, 0.14 / self.speed_multiplier)
        self.row_pause = (0.35 / self.speed_multiplier, 0.95 / self.speed_multiplier)
        self.in_cell_newline_pause = (0.15 / self.speed_multiplier, 0.35 / self.speed_multiplier)

        # Typo parameters
        self.typo_probability = 0.05
        self.typo_type_weights = {
            'substitution': 0.48,   # hit an adjacent neighbor key
            'doubling': 0.18,       # press the same key twice
            'insertion': 0.12,      # extra neighbor key before the real key
            'transposition': 0.12,  # swap two adjacent letters
            'omission': 0.10,       # skip a letter, then catch up
        }
        self.typo_notice_delay = (0.08, 0.32)
        self.typo_retype_delay = (0.04, 0.13)

        # Burst typing tokens for spreadsheet formulas and common values
        self.burst_tokens = [
            "=SUM(", "=AVERAGE(", "=COUNT(", "=IF(", "=VLOOKUP(", "=XLOOKUP(",
            "=MAX(", "=MIN(", "=SUBTOTAL(", "TRUE", "FALSE", "True", "False",
            "Pending", "Delivered", "Shipped", "Active", "Completed", "Processing",
            "In Stock", "Out of Stock", "Total", "Average", "USD", "EUR", "None", "NULL", "N/A",
            "2024", "2025", "2026", "http://", "https://", ".com", ".org",
        ]
        self.burst_speed_multiplier = 0.45

        # Warmup & attention drift
        self.warmup_chars = 140
        self.warmup_multiplier = 1.38
        self.rhythm_drift_interval = 45
        self.rhythm_drift_sigma = 0.09
        self.rhythm_offset_min = 0.78
        self.rhythm_offset_max = 1.28

        # Cognitive & distraction pauses
        self.pause_after_word = (0.05 / self.speed_multiplier, 0.18 / self.speed_multiplier)
        self.pause_thinking_prob = 0.014
        self.pause_thinking_duration = (0.7, 2.5)
        self.distraction_probability = 0.0006
        self.distraction_duration = (3.5, 8.5)

        # Fatigue model
        self.fatigue_onset_chars = 350
        self.fatigue_slowdown_factor = 0.012
        self.fatigue_typo_multiplier = 2.0

        # Mouse behavior
        self.mouse_drift_probability = 0.04

        # Complete keyboard neighbor map for authentic typos
        self.key_neighbors = {
            'a': 'sqwz', 'b': 'vghn', 'c': 'xdfv', 'd': 'serfcx',
            'e': 'wsdfr', 'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb',
            'i': 'ujkol', 'j': 'huiknm', 'k': 'jiolm', 'l': 'kop',
            'm': 'njk', 'n': 'bhjm', 'o': 'iklp', 'p': 'ol',
            'q': 'wa', 'r': 'edft', 's': 'awedxz', 't': 'rfgy',
            'u': 'yhjki', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc',
            'y': 'tghu', 'z': 'asx',
            '0': '9o-p', '1': '2q', '2': '13wq', '3': '24we', '4': '35er',
            '5': '46rt', '6': '57ty', '7': '68yu', '8': '79ui', '9': '80io',
            '-': '0=p', '=': '-][', '.': ',>/', ',': 'm<.l',
        }

        self.slow_digraphs = {
            'zx', 'xz', 'qp', 'pq', 'zq', 'qz', 'bf', 'fb', 'gn', 'ng', 'mj', 'jm',
            'aq', 'qa', 'pl', 'lp',
        }
        self.fast_digraphs = {
            'th', 'he', 'in', 'er', 'an', 'en', 'on', 'at', 'es', 'ed',
            'te', 'ti', 'or', 'st', 'ar', 'nd', 'to', 'nt', 'is', 'of',
            'al', 'as', 'ha', 'se', 'ou', 're', 'ne', 'ea', 'ri', 'de',
        }


# ──────────────────────────────────────────────
#  Core Excel Typer Engine
# ──────────────────────────────────────────────

class ExcelTyper:
    """Simulates authentic human typing directly into an active Excel sheet."""

    def __init__(self, profile: ExcelTypingProfile = None, guard: WindowGuard = None):
        self.profile = profile or ExcelTypingProfile()
        self.guard = guard
        self.mouse = HumanMouseSimulator()
        self.chars_typed = 0
        self.cells_typed = 0
        self.rows_typed = 0

        self._stop_event = threading.Event()
        self._periodic_callback = None
        self._rhythm_offset = 1.0
        self._next_rhythm_drift = random.randint(30, 70)

    def stop(self):
        self._stop_event.set()

    def reset_fatigue(self):
        self.chars_typed = 0

    def _fatigue_factor(self) -> float:
        p = self.profile
        if self.chars_typed <= p.fatigue_onset_chars:
            return 0.0
        return (self.chars_typed - p.fatigue_onset_chars) / 100.0

    def _warmup_factor(self) -> float:
        p = self.profile
        if self.chars_typed >= p.warmup_chars:
            return 1.0
        rem = 1.0 - (self.chars_typed / max(1, p.warmup_chars))
        return 1.0 + (p.warmup_multiplier - 1.0) * (rem ** 2)

    def _update_rhythm_drift(self):
        p = self.profile
        if self.chars_typed >= self._next_rhythm_drift:
            self._rhythm_offset *= random.lognormvariate(0.0, p.rhythm_drift_sigma)
            self._rhythm_offset = max(
                p.rhythm_offset_min, min(self._rhythm_offset, p.rhythm_offset_max)
            )
            self._next_rhythm_drift = self.chars_typed + random.randint(30, 80)

    def _sample_dwell(self, char: str) -> float:
        p = self.profile
        dwell = random.lognormvariate(
            math.log(max(0.02, p.dwell_mean)),
            p.dwell_sigma * random.uniform(0.85, 1.15)
        )
        dwell *= KEY_DWELL_BIAS.get(char.lower(), 1.0)
        dwell *= 1.0 + (self._warmup_factor() - 1.0) * 0.20
        dwell *= 1.0 + self._fatigue_factor() * 0.003
        return max(0.035, min(dwell, 0.25))

    def _get_inter_key_delay(self, prev_char: str, curr_char: str) -> float:
        p = self.profile
        self._update_rhythm_drift()

        base = random.lognormvariate(
            math.log((p.base_delay_min + p.base_delay_max) / 2),
            random.uniform(0.28, 0.38)
        )
        base = max(p.base_delay_min * 0.85, min(base, p.base_delay_max * 2.0))

        digraph = (prev_char + curr_char).lower()
        if digraph in p.fast_digraphs:
            base *= random.uniform(0.55, 0.70)
        elif digraph in p.slow_digraphs:
            base *= random.uniform(1.30, 1.60)

        prev_base = prev_char.lower() if len(prev_char) == 1 else ''
        curr_base = curr_char.lower() if len(curr_char) == 1 else ''
        pf = KEY_FINGER.get(prev_base)
        cf = KEY_FINGER.get(curr_base)
        if pf is not None and cf is not None:
            if pf == cf:
                base *= random.uniform(1.18, 1.40)
            elif (pf < 4) == (cf < 4):
                base *= random.uniform(1.02, 1.10)
            else:
                base *= random.uniform(0.88, 0.98)

        base *= KEY_DIFFICULTY.get(curr_base, 1.0)
        if curr_char.isdigit():
            base *= random.uniform(1.04, 1.16)
        if curr_char.isupper() or curr_char in '!@#$%^&*()_+{}|:"<>?~':
            base += random.uniform(0.02, 0.055)

        base *= self._warmup_factor()
        base *= self._rhythm_offset

        fatigue = self._fatigue_factor()
        if fatigue > 0:
            base *= 1.0 + fatigue * p.fatigue_slowdown_factor * random.uniform(0.8, 1.2)

        base = max(0.015, base + random.gauss(0, 0.005))
        return base

    def _type_char(self, char: str, dwell: float):
        _os_type_char_with_dwell(char, dwell)

    def _backspace(self):
        _os_press_special('backspace', random.uniform(0.04, 0.10))

    def _neighbor_typo(self, char: str) -> str:
        neighbors = self.profile.key_neighbors.get(char.lower(), '')
        if not neighbors:
            return None
        typo = random.choice(neighbors)
        return typo.upper() if char.isupper() else typo

    def _check_burst_token(self, text: str, position: int) -> str:
        """Checks if the text at position starts with a burst-typeable spreadsheet token or formula."""
        remaining = text[position:]
        for token in sorted(self.profile.burst_tokens, key=len, reverse=True):
            if remaining.startswith(token):
                return token
        return None

    def _choose_typo_type(self) -> str:
        """Samples one of the 5 authentic human mistake types based on profile weights."""
        weights = self.profile.typo_type_weights
        kinds = list(weights.keys())
        return random.choices(kinds, weights=[weights[k] for k in kinds], k=1)[0]

    def _type_key(self, char: str, prev_char: str,
                  delay_scale: float = 1.0, dwell_scale: float = 1.0) -> str:
        delay = self._get_inter_key_delay(prev_char, char) * delay_scale
        time.sleep(delay)
        self._type_char(char, self._sample_dwell(char) * dwell_scale)
        self.chars_typed += 1
        return char

    def _emit_typo(self, char: str, next_char: str, prev_char: str) -> int:
        """
        Executes one realistic mistake and its immediate human-like correction.
        5-way model:
          1. Substitution: Hit an adjacent key, notice, backspace, retype.
          2. Doubling: Key pressed twice due to heavy tap, notice, backspace once.
          3. Insertion: Stray neighbor key pressed immediately before correct key.
          4. Omission: Skipped a character, typed next character, noticed, backspaced, typed both.
          5. Transposition: Swapped two adjacent characters, backspaced twice, typed correctly.
        Returns the number of source characters consumed (1 or 2), or 0 if skipped.
        """
        p = self.profile
        kind = self._choose_typo_type()

        def notice():
            time.sleep(random.uniform(*p.typo_notice_delay))

        def fix():
            self._backspace()
            time.sleep(random.uniform(*p.typo_retype_delay))

        if kind == 'substitution':
            wrong = self._neighbor_typo(char)
            if not wrong or wrong == char:
                return 0
            self._type_key(wrong, prev_char, delay_scale=0.9)
            notice()
            fix()
            self._type_key(char, wrong, delay_scale=0.8)
            return 1

        if kind == 'doubling':
            self._type_key(char, prev_char, delay_scale=0.9)
            self._type_key(char, char, delay_scale=0.6, dwell_scale=0.9)
            notice()
            fix()
            return 1

        if kind == 'insertion':
            wrong = self._neighbor_typo(char)
            if not wrong or wrong == char:
                return 0
            self._type_key(wrong, prev_char, delay_scale=0.9)
            notice()
            fix()
            self._type_key(char, wrong, delay_scale=0.8)
            return 1

        if kind == 'omission':
            if not next_char or not (next_char.isalnum() or next_char in '.-_'):
                return 0
            # Skip this character, type the next one, notice mistake, fix, and retype both
            self._type_key(next_char, prev_char, delay_scale=0.9)
            notice()
            fix()
            self._type_key(char, prev_char, delay_scale=0.8)
            self._type_key(next_char, char, delay_scale=0.9)
            return 2

        if kind == 'transposition':
            if not next_char or not (next_char.isalnum() or next_char in '.-_'):
                return 0
            # Type pair in reverse order, notice, backspace twice, retype correctly
            self._type_key(next_char, prev_char, delay_scale=0.9)
            self._type_key(char, next_char, delay_scale=0.8)
            notice()
            fix()
            fix()
            self._type_key(char, prev_char, delay_scale=0.8)
            self._type_key(next_char, char, delay_scale=0.9)
            return 2

        return 0

    def type_cell_text(self, text: str) -> bool:
        """
        Types the string content of a single Excel cell with full human-like biometrics:
          - Burst typing for Excel formulas and common spreadsheet values
          - 5-way human typo model (substitution, doubling, insertion, omission, transposition)
          - Natural thinking and cognitive pauses
          - Post-character punctuation pauses (., :, ;, (), [], {}, etc.)
          - Distraction pauses (phone notification, looking away)
          - Mouse micro-movements and drift
          - Alt+Enter for in-cell line breaks
          - Auto-pause when window focus changes (resumes cleanly when Excel is refocused)
        """
        p = self.profile
        prev_char = ''
        i = 0

        while i < len(text):
            if self._stop_event.is_set():
                return False

            # Focus guard: if window changed, pause safely until Excel is refocused
            if self.guard and not self.guard.pause_until_focused(self._stop_event):
                return False

            char = text[i]

            # In-cell line break (Excel multiline cell)
            if char == '\r':
                i += 1
                continue
            if char == '\n':
                time.sleep(random.uniform(*p.in_cell_newline_pause))
                # Press Alt + Enter for in-cell newline
                _os_hotkey('lalt', 'enter')
                time.sleep(random.uniform(*p.in_cell_newline_pause))
                prev_char = ''
                i += 1
                continue

            # Check for burst token (Excel formula prefixes, common keywords, dates, status words)
            burst = self._check_burst_token(text, i)
            if burst and len(burst) >= 3 and random.random() < 0.72:
                burst_mult = p.burst_speed_multiplier * random.uniform(0.85, 1.15)
                for bc in burst:
                    if self._stop_event.is_set():
                        return False
                    if self.guard and not self.guard.pause_until_focused(self._stop_event):
                        return False
                    self._type_key(bc, prev_char, delay_scale=burst_mult)
                    prev_char = bc
                i += len(burst)
                # Word-level pause after completing burst token
                time.sleep(random.uniform(*p.pause_after_word))
                continue

            # Distraction pause (e.g. phone notification, looking away for a few seconds)
            if random.random() < p.distraction_probability:
                distract_dur = random.uniform(*p.distraction_duration)
                if random.random() < 0.4:
                    self.mouse.idle_drift()
                time.sleep(distract_dur)

            # Random cognitive / thinking pause
            if random.random() < p.pause_thinking_prob:
                time.sleep(random.uniform(*p.pause_thinking_duration))

            # Mouse micro-movement / drift
            if random.random() < p.mouse_drift_probability:
                self.mouse.idle_drift()

            # Typo injection (with fatigue scaling and 5 error types)
            typo_prob = p.typo_probability
            fatigue = self._fatigue_factor()
            if fatigue > 0:
                typo_prob *= 1.0 + min(fatigue, 4.0) * p.fatigue_typo_multiplier
            typo_prob = min(typo_prob, 0.12)

            next_char = text[i + 1] if i + 1 < len(text) else ''
            if (char.isalnum() and random.random() < typo_prob and i > 1):
                consumed = self._emit_typo(char, next_char, prev_char)
                if consumed > 0:
                    prev_char = text[i + consumed - 1]
                    i += consumed
                    continue

            # Normal keystroke
            self._type_key(char, prev_char)

            # Post-character pauses on punctuation & word boundaries
            if char in '.;:':
                time.sleep(random.uniform(0.12, 0.35) / p.speed_multiplier)
            elif char in ',':
                time.sleep(random.uniform(0.06, 0.16) / p.speed_multiplier)
            elif char in '()[]{}':
                time.sleep(random.uniform(0.08, 0.22) / p.speed_multiplier)
            elif char == ' ':
                if random.random() < 0.15:
                    time.sleep(random.uniform(0.18, 0.45) / p.speed_multiplier)
                else:
                    time.sleep(random.uniform(*p.pause_after_word))

            prev_char = char
            i += 1

            # Check for rest break at word boundaries
            if char == ' ' and self._periodic_callback is not None:
                self._periodic_callback()

        self.cells_typed += 1
        if self._periodic_callback is not None:
            self._periodic_callback()
        return True

    def commit_cell_tab(self):
        """Commits current cell and advances to next column."""
        _os_press_special('tab')
        time.sleep(random.uniform(*self.profile.cell_settle_delay))

    def commit_row_enter(self):
        """Commits final cell and returns to the first column on the next row."""
        _os_press_special('enter')
        time.sleep(random.uniform(*self.profile.row_pause))
        self.rows_typed += 1

    def move_arrow(self, direction: str):
        """Moves active cell selection using arrow keys ('right', 'down', 'left', 'up')."""
        _os_press_special(direction)
        time.sleep(random.uniform(*self.profile.cell_settle_delay))

    def save_workbook(self):
        """Sends Ctrl+S to save the Excel workbook."""
        print("  [Auto-Save] Saving workbook (Ctrl+S)...")
        _os_hotkey('lctrl', 's')
        time.sleep(random.uniform(0.6, 1.2))

    def close_workbook(self):
        """Sends Ctrl+W to close the active workbook in Excel."""
        print("  [Workbook] Closing workbook (Ctrl+W)...")
        _os_hotkey('lctrl', 'w')
        time.sleep(random.uniform(0.8, 1.5))

    def clear_active_sheet(self):
        """Selects all cells (Ctrl+A) and deletes to reset partially typed sheets."""
        _os_hotkey('lctrl', 'a')
        time.sleep(random.uniform(0.08, 0.16))
        _os_press_special('delete')
        time.sleep(random.uniform(0.12, 0.25))


# ──────────────────────────────────────────────
#  Data Reader & Universal CSV Ingestion
# ──────────────────────────────────────────────

import io

# Expand CSV field size limit to support massive text cells
try:
    csv.field_size_limit(2147483647)
except OverflowError:
    csv.field_size_limit(sys.maxsize)


def detect_file_encoding(filepath: str) -> str:
    """
    Auto-detects the encoding of a CSV or text file.
    Handles UTF-8 (with or without BOM), UTF-16 LE/BE, and Windows ANSI (CP1252/Latin-1).
    """
    with open(filepath, 'rb') as f:
        raw_prefix = f.read(4)

    # Check Byte Order Marks (BOM)
    # Using 'utf-16' (without -le/-be) causes Python to strip the BOM automatically
    if raw_prefix.startswith(b'\xef\xbb\xbf'):
        return 'utf-8-sig'
    elif raw_prefix.startswith(b'\xff\xfe') or raw_prefix.startswith(b'\xfe\xff'):
        return 'utf-16'

    # Read a sample chunk to test decoders
    with open(filepath, 'rb') as f:
        sample = f.read(65536)

    # Try UTF-8 first (standard for modern CSVs)
    try:
        sample.decode('utf-8')
        return 'utf-8'
    except UnicodeDecodeError:
        pass

    # Try CP1252 (standard Windows Excel ANSI export)
    try:
        sample.decode('cp1252')
        return 'cp1252'
    except UnicodeDecodeError:
        pass

    # Universal fallback that never raises decode errors
    return 'latin-1'


def load_matrix_from_csv(filepath: str, delimiter: str = None,
                         encoding: str = None, pad_columns: bool = True,
                         strip_cells: bool = False) -> list:
    """
    Universal CSV / TSV parser supporting:
      - All delimiters: comma (,), semicolon (;), tab (\\t), pipe (|), colon (:)
      - All encodings: UTF-8, UTF-8-BOM, UTF-16, CP1252, Latin-1
      - RFC 4180 multiline cells (cells with newlines inside quotes)
      - Escaped quotes (both "" and \\")
      - Ragged rows (automatically padded to equal column width)
    """
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Source file not found: {filepath}")

    detected_enc = encoding or detect_file_encoding(filepath)

    with open(filepath, 'r', encoding=detected_enc, errors='replace') as f:
        content = f.read()

    # Strip any stray leading BOM character so it is never typed into Excel
    if content.startswith('\ufeff'):
        content = content[1:]

    if not content.strip():
        return []

    # Delimiter auto-detection across all standard spreadsheet delimiters
    if not delimiter:
        # Check first 8KB sample for delimiter sniffing
        sample = content[:8192]
        try:
            sniffer = csv.Sniffer()
            dialect = sniffer.sniff(sample, delimiters=[',', ';', '\t', '|', ':'])
            delimiter = dialect.delimiter
        except Exception:
            # Fallback heuristic: count common delimiters in the first line
            first_line = content.split('\n')[0] if '\n' in content else content
            counts = {
                ',': first_line.count(','),
                ';': first_line.count(';'),
                '\t': first_line.count('\t'),
                '|': first_line.count('|'),
            }
            best_delimiter = max(counts, key=counts.get)
            delimiter = best_delimiter if counts[best_delimiter] > 0 else ','

    # Parse full file with RFC 4180 multiline support via io.StringIO
    matrix = []
    stream = io.StringIO(content)
    reader = csv.reader(stream, delimiter=delimiter, skipinitialspace=False)

    for row in reader:
        # Handle empty lines
        if not row:
            continue
        if strip_cells:
            matrix.append([str(c).strip() for c in row])
        else:
            matrix.append([str(c) for c in row])

    # Pad ragged rows to ensure every row has the same number of columns
    if pad_columns and matrix:
        max_cols = max(len(row) for row in matrix)
        for row in matrix:
            while len(row) < max_cols:
                row.append("")

    return matrix


def load_matrix_from_json(filepath: str) -> list:
    """Reads JSON list-of-lists or list-of-dicts into a 2D matrix."""
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if isinstance(data, list):
        if not data:
            return []
        if isinstance(data[0], list):
            return [[str(c) for c in row] for row in data]
        elif isinstance(data[0], dict):
            headers = list(data[0].keys())
            rows = [headers]
            for item in data:
                rows.append([str(item.get(h, '')) for h in headers])
            return rows
    raise ValueError("JSON must be an array of arrays or array of objects.")


def get_excel_executable_path() -> str:
    """Finds the absolute path to excel.exe on Windows."""
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'Software\Microsoft\Windows\CurrentVersion\App Paths\excel.exe'
        )
        val, _ = winreg.QueryValueEx(key, '')
        winreg.CloseKey(key)
        if os.path.exists(val):
            return val
    except Exception:
        pass

    common_paths = [
        r'C:\Program Files\Microsoft Office\Root\Office16\EXCEL.EXE',
        r'C:\Program Files (x86)\Microsoft Office\Root\Office16\EXCEL.EXE',
        r'C:\Program Files\Microsoft Office\Office16\EXCEL.EXE',
        r'C:\Program Files (x86)\Microsoft Office\Office16\EXCEL.EXE',
        r'C:\Program Files\Microsoft Office\Office15\EXCEL.EXE',
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p
    return 'excel'


def launch_and_focus_excel(target_file: str = None, timeout: float = 15.0) -> tuple:
    """
    Launches Microsoft Excel automatically, waits for it to open and focus,
    and positions cursor on cell A1.
    Returns (hwnd, window_title).
    """
    excel_bin = get_excel_executable_path()

    if target_file:
        abs_dest = os.path.abspath(target_file)
        parent_dir = os.path.dirname(abs_dest)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)

        base_name = os.path.basename(abs_dest)
        ext = os.path.splitext(abs_dest)[1].lower()

        # If file doesn't exist, create an empty starter file
        if not os.path.exists(abs_dest):
            if ext in ('.csv', '.tsv', '.txt'):
                with open(abs_dest, 'w', encoding='utf-8') as f:
                    pass
            elif ext in ('.xlsx', '.xls'):
                try:
                    import openpyxl
                    wb = openpyxl.Workbook()
                    wb.save(abs_dest)
                except ImportError:
                    with open(abs_dest, 'w', encoding='utf-8') as f:
                        pass

        print(f"  [Excel] Launching Microsoft Excel with: {base_name}...")
        try:
            subprocess.Popen([excel_bin, abs_dest])
        except Exception:
            try:
                os.startfile(abs_dest)
            except Exception:
                subprocess.Popen(f'start "" "{abs_dest}"', shell=True)
        search_pattern = base_name
    else:
        # Check if Excel is already running
        existing = [w for w in _list_windows() if is_excel_window(w)]
        if existing:
            hwnd = existing[0]['hwnd']
            title = existing[0]['title']
            _focus_window(hwnd)
            time.sleep(0.5)
            _os_hotkey('lctrl', 'home')
            print(f"  [Excel] Found running Excel window: {_safe_text(title)} (Cell A1 focused)")
            return hwnd, title

        print(f"  [Excel] Launching Microsoft Excel (new workbook)...")
        try:
            subprocess.Popen([excel_bin])
        except Exception:
            subprocess.Popen(['cmd.exe', '/c', 'start', 'excel'], shell=False)
        search_pattern = "Excel"

    # Wait for Excel window to appear and take focus
    start_time = time.time()
    while time.time() - start_time < timeout:
        matches = [w for w in _list_windows() if is_excel_window(w, pattern=search_pattern)]
        if not matches and (time.time() - start_time > 6.0):
            matches = [w for w in _list_windows() if is_excel_window(w, pattern='excel')]

        if matches:
            hwnd = matches[0]['hwnd']
            title = matches[0]['title']
            if _focus_window(hwnd):
                time.sleep(1.2)  # Allow Excel grid to finish rendering
                _os_hotkey('lctrl', 'home')
                time.sleep(0.3)
                print(f"  [Excel] ✓ Excel opened and focused: {_safe_text(title)} (Cell A1 active)")
                return hwnd, title
        time.sleep(0.3)

    print(f"  [Excel] Warning: Could not confirm Excel focus within {timeout}s.")
    return None, search_pattern


def get_sample_inventory_data() -> list:
    """Generates a realistic business/inventory dataset with Excel formulas."""
    return [
        ["Product Code", "Item Description", "Category", "Units Sold", "Unit Price", "Total Revenue", "Status"],
        ["SKU-1001", "Ergonomic Mechanical Keyboard", "Hardware", "14", "129.99", "=D2*E2", "Shipped"],
        ["SKU-1002", "Ultra-Wide Gaming Monitor 34\"", "Displays", "6", "449.50", "=D3*E3", "Delivered"],
        ["SKU-1003", "Noise-Cancelling Headphones", "Audio", "22", "89.00", "=D4*E4", "Processing"],
        ["SKU-1004", "USB-C Multiport Dock", "Accessories", "35", "54.25", "=D5*E5", "Shipped"],
        ["SKU-1005", "Precision Wireless Mouse", "Hardware", "41", "39.99", "=D6*E6", "Delivered"],
        ["SKU-1006", "Adjustable Laptop Riser", "Office", "18", "28.50", "=D7*E7", "Pending"],
        ["SKU-1007", "4K Webcam w/ Privacy Shutter", "Video", "12", "79.99", "=D8*E8", "Shipped"],
        ["SKU-1008", "Desk Mat Extended (90x40cm)", "Accessories", "50", "19.99", "=D9*E9", "Delivered"],
    ]


# ──────────────────────────────────────────────
#  Replication Orchestrator
# ──────────────────────────────────────────────

class ExcelProjectTyper:
    """Orchestrates row-by-row and cell-by-cell typing into Excel with recovery state."""

    PROGRESS_FILE = "excel_typer_progress.json"

    def __init__(self, matrix: list, profile: ExcelTypingProfile,
                 guard: WindowGuard = None, nav_mode: str = "tab_enter",
                 save_interval: int = 10, source_name: str = "custom_data",
                 break_interval: tuple = (45, 60), break_duration: tuple = (3, 4),
                 no_breaks: bool = False, stop_minutes: float = None):
        self.matrix = matrix
        self.profile = profile
        self.guard = guard
        self.nav_mode = nav_mode
        self.save_interval = save_interval
        self.source_name = source_name
        self.break_interval_range = break_interval
        self.break_duration_range = break_duration
        self.no_breaks = no_breaks
        self.stop_minutes = stop_minutes
        self.stop_seconds = float(stop_minutes) * 60.0 if stop_minutes else None

        self.typer = ExcelTyper(profile=self.profile, guard=self.guard)
        self.typer._periodic_callback = self._periodic_check

        self.session_start = time.time()
        self.last_break_time = time.time()
        self.next_break_interval = random.uniform(
            self.break_interval_range[0] * 60, self.break_interval_range[1] * 60
        )

    def _is_time_up(self) -> bool:
        if not self.stop_seconds:
            return False
        return (time.time() - self.session_start) >= self.stop_seconds

    def _periodic_check(self) -> bool:
        if self._is_time_up():
            self.typer.stop()
            return True
        return self._take_break_if_needed()

    def _save_progress(self, row_idx: int, total_rows: int):
        state = {
            'mode': 'single',
            'source': self.source_name,
            'current_row': row_idx,
            'total_rows': total_rows,
            'completed': row_idx >= total_rows - 1,
            'cells_typed': self.typer.cells_typed,
            'characters_typed': self.typer.chars_typed,
            'timestamp': datetime.now().isoformat(),
        }
        try:
            with open(self.PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"  [Progress] Warning: Could not save progress: {e}")

    def _take_break_if_needed(self) -> bool:
        """
        Checks if typing has been active for 45-60 minutes.
        If so, takes a random 3-4 minute human rest break with a live countdown timer.
        Returns True if a break was taken.
        """
        if self.no_breaks:
            return False
        elapsed_work = time.time() - self.last_break_time
        if elapsed_work < self.next_break_interval:
            return False

        duration_sec = random.uniform(
            self.break_duration_range[0] * 60, self.break_duration_range[1] * 60
        )
        duration_min = duration_sec / 60.0
        work_mins = elapsed_work / 60.0
        resume_dt = datetime.fromtimestamp(time.time() + duration_sec).strftime('%H:%M:%S')

        print(f"\n\n{'☕ '*25}")
        print(f"  HUMAN REST BREAK")
        print(f"  Session typing time: {work_mins:.1f} minutes")
        print(f"  Taking a break for:  {duration_min:.1f} minutes ({int(duration_sec)} seconds)")
        print(f"  Resuming at:         {resume_dt}")
        print(f"{'☕ '*25}\n")

        start_break = time.time()
        while (time.time() - start_break) < duration_sec:
            if self.typer._stop_event.is_set():
                self.last_break_time = time.time()
                return True
            remaining = int(duration_sec - (time.time() - start_break))
            mins_rem = remaining // 60
            secs_rem = remaining % 60
            print(f"  Sleeping... {mins_rem:02d}:{secs_rem:02d} remaining (Press Ctrl+C to abort)  ", end='\r')
            time.sleep(1)

        print(f"\n\n  ✓ Break finished! Continuing typing...\n")

        # Reset fatigue after rest
        self.typer.reset_fatigue()

        # Re-focus target window if needed
        if self.guard:
            self.guard.ensure_focus()

        # Schedule next random 45-60 minute typing session
        self.last_break_time = time.time()
        self.next_break_interval = random.uniform(
            self.break_interval_range[0] * 60, self.break_interval_range[1] * 60
        )
        print(f"  Next break scheduled in ~{self.next_break_interval / 60.0:.1f} minutes.\n")
        return True

    def run(self, start_row: int = 0, start_col: int = 0, max_rows: int = None,
            initial_delay: float = 5.0) -> bool:
        total_rows = len(self.matrix)
        if total_rows == 0:
            print("  [ERROR] Matrix is empty — nothing to type.")
            return False

        end_row = total_rows if max_rows is None else min(total_rows, start_row + max_rows)

        print(f"\n{'═'*65}")
        print(f"  EXCEL TYPER — HUMAN-LIKE SPREADSHEET AUTOMATION")
        print(f"  Rows to type: {end_row - start_row} (Rows {start_row+1} to {end_row})")
        print(f"  Navigation:   {self.nav_mode.upper()} mode")
        print(f"  Speed factor: {self.profile.speed_multiplier:.1f}x")
        if self.stop_minutes:
            stop_dt = datetime.fromtimestamp(self.session_start + self.stop_seconds).strftime('%H:%M:%S')
            print(f"  Stop limit:   {self.stop_minutes:.1f} minutes (will stop at {stop_dt})")
        else:
            print(f"  Stop limit:   None (runs continuously)")
        if not self.no_breaks:
            first_mins = self.next_break_interval / 60.0
            first_dt = datetime.fromtimestamp(time.time() + self.next_break_interval).strftime('%H:%M:%S')
            print(f"  Breaks:       Random {self.break_duration_range[0]:.0f}-{self.break_duration_range[1]:.0f}m rest every {self.break_interval_range[0]:.0f}-{self.break_interval_range[1]:.0f}m")
            print(f"  First break:  ~{first_mins:.1f} minutes (at {first_dt})")
        if self.guard:
            print(f"  Focus Guard:  {self.guard.summary()}")
        print(f"{'═'*65}\n")

        # Focus / position on cell A1
        if self.guard and self.guard.hwnd:
            self.guard.ensure_focus()
            _os_hotkey('lctrl', 'home')
            time.sleep(0.2)

        print(f"  [Excel] Ready on active worksheet (Cell A1 focused).")
        print(f"  Press Ctrl+C to halt at any moment.\n")
        if initial_delay > 0:
            for i in range(int(initial_delay), 0, -1):
                if self.typer._stop_event.is_set():
                    return False
                print(f"  Starting in {i}...", end='\r')
                time.sleep(1)
        print("  Typing actively engaged!                      \n")

        for r_idx in range(start_row, end_row):
            if self.typer._stop_event.is_set() or self._is_time_up():
                if self._is_time_up():
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*65}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at row {r_idx + 1} of {total_rows}.")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*65}\n")
                    self.typer.save_workbook()
                    self._save_progress(r_idx - 1, total_rows)
                    return True
                else:
                    print(f"\n[Interrupted] Stopped before row {r_idx+1}.")
                    self._save_progress(r_idx - 1, total_rows)
                    return False

            # Ensure focus before row starts
            if self.guard and not self.guard.ensure_focus():
                print(f"  [FOCUS] Lost window focus at row {r_idx+1}. Pausing execution.")
                self._save_progress(r_idx - 1, total_rows)
                return False

            row = self.matrix[r_idx]
            col_start = start_col if r_idx == start_row else 0
            num_cols = len(row)

            print(f"  [Row {r_idx+1}/{total_rows}] Typing {num_cols - col_start} cells...", end='')
            row_start_time = time.time()

            for c_idx in range(col_start, num_cols):
                if self.typer._stop_event.is_set():
                    self._save_progress(r_idx - 1, total_rows)
                    return False

                cell_value = row[c_idx]

                # Type cell contents if not blank
                if cell_value:
                    success = self.typer.type_cell_text(cell_value)
                    if not success:
                        self._save_progress(r_idx - 1, total_rows)
                        return False
                else:
                    # Quick glance on empty cell
                    time.sleep(random.uniform(*self.profile.empty_cell_glance))

                # Navigation to next cell or next row
                is_last_col = (c_idx == num_cols - 1)

                if self.nav_mode == "tab_enter":
                    if not is_last_col:
                        self.typer.commit_cell_tab()
                    else:
                        self.typer.commit_row_enter()
                else:
                    # Arrow key mode
                    if not is_last_col:
                        self.typer.move_arrow('right')
                    else:
                        # Move down and jump back to row start
                        self.typer.move_arrow('down')
                        # Return to first column (press Home or left arrows)
                        _os_press_special('home')
                        time.sleep(random.uniform(*self.profile.row_pause))

            row_elapsed = time.time() - row_start_time
            print(f" done ({row_elapsed:.1f}s)")

            # Save progress after every row
            self._save_progress(r_idx, total_rows)

            # Check if time limit was reached
            if self._is_time_up():
                elapsed_m = (time.time() - self.session_start) / 60.0
                print(f"\n\n{'═'*65}")
                print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                print(f"  Session ran for {elapsed_m:.1f} minutes.")
                print(f"  Progress cleanly saved at row {r_idx + 1} of {total_rows}.")
                print(f"  Run the command again anytime to auto-resume!")
                print(f"{'═'*65}\n")
                self.typer.save_workbook()
                return True

            # Auto-save workbook periodically
            if self.save_interval and ((r_idx + 1) % self.save_interval == 0):
                self.typer.save_workbook()

            # Rest break check
            self._take_break_if_needed()

        print(f"\n{'═'*65}")
        print(f"  EXCEL TYPER COMPLETE")
        print(f"  Total Rows:       {self.typer.rows_typed}")
        print(f"  Total Cells:      {self.typer.cells_typed}")
        print(f"  Characters Typed: {self.typer.chars_typed}")
        total_time = time.time() - self.session_start
        print(f"  Session Duration: {total_time:.1f} seconds")
        print(f"{'═'*65}\n")
        return True


# ──────────────────────────────────────────────
#  Folder Scanner & Batch Replicator
# ──────────────────────────────────────────────

class SpreadsheetFolderScanner:
    """Recursively scans a source folder for tabular spreadsheet files."""

    DEFAULT_EXTENSIONS = {'.csv', '.tsv', '.txt', '.xlsx', '.xls', '.json'}
    DEFAULT_SKIP_DIRS = {'.git', '__pycache__', 'node_modules', '.vs', 'bin', 'obj'}

    def __init__(self, source_dir: str, extensions: set = None, skip_dirs: set = None):
        self.source_dir = os.path.abspath(source_dir)
        self.extensions = extensions or self.DEFAULT_EXTENSIONS
        self.skip_dirs = skip_dirs or self.DEFAULT_SKIP_DIRS

    def scan(self) -> list:
        files = []
        for root, dirs, filenames in os.walk(self.source_dir):
            dirs[:] = [d for d in dirs if d not in self.skip_dirs]
            dirs.sort()

            for fname in sorted(filenames):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in self.extensions:
                    continue

                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, self.source_dir)

                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    continue

                files.append({
                    'relative_path': rel_path,
                    'absolute_path': abs_path,
                    'size_bytes': size,
                    'extension': ext,
                })
        return files


class ExcelFolderReplicator:
    """Replicates an entire folder structure of spreadsheets into a destination folder."""

    PROGRESS_FILE = "excel_typer_progress.json"

    def __init__(self, source_dir: str, target_dir: str, files: list,
                 profile: ExcelTypingProfile, guard: WindowGuard = None,
                 nav_mode: str = "tab_enter", save_interval: int = 10,
                 confirm_each: bool = False,
                 break_interval: tuple = (45, 60), break_duration: tuple = (3, 4),
                 no_breaks: bool = False, delimiter: str = None,
                 encoding: str = None, pad_columns: bool = True, strip_cells: bool = False,
                 stop_minutes: float = None):
        self.source_dir = os.path.abspath(source_dir)
        self.target_dir = os.path.abspath(target_dir)
        self.files = files
        self.profile = profile
        self.guard = guard
        self.nav_mode = nav_mode
        self.save_interval = save_interval
        self.confirm_each = confirm_each
        self.break_interval_range = break_interval
        self.break_duration_range = break_duration
        self.no_breaks = no_breaks
        self.delimiter = delimiter
        self.encoding = encoding
        self.pad_columns = pad_columns
        self.strip_cells = strip_cells
        self.stop_minutes = stop_minutes
        self.stop_seconds = float(stop_minutes) * 60.0 if stop_minutes else None

        self.typer = ExcelTyper(profile=self.profile, guard=self.guard)
        self.typer._periodic_callback = self._periodic_check
        self.session_start = time.time()
        self.last_break_time = time.time()
        self.next_break_interval = random.uniform(
            self.break_interval_range[0] * 60, self.break_interval_range[1] * 60
        )

    def _is_time_up(self) -> bool:
        if not self.stop_seconds:
            return False
        return (time.time() - self.session_start) >= self.stop_seconds

    def _periodic_check(self) -> bool:
        if self._is_time_up():
            self.typer.stop()
            return True
        return self._take_break_if_needed()

    def _create_target_structure(self):
        dirs_created = set()
        for f in self.files:
            target_path = os.path.join(self.target_dir, f['relative_path'])
            target_dir = os.path.dirname(target_path)
            if target_dir not in dirs_created:
                os.makedirs(target_dir, exist_ok=True)
                dirs_created.add(target_dir)

    def _save_progress(self, file_idx: int, total_files: int, current_file: str, completed: bool = False):
        state = {
            'mode': 'folder',
            'source_dir': self.source_dir,
            'destination_dir': self.target_dir,
            'file_index': file_idx,
            'total_files': total_files,
            'current_file': current_file,
            'completed': completed,
            'total_cells_typed': self.typer.cells_typed,
            'total_chars_typed': self.typer.chars_typed,
            'timestamp': datetime.now().isoformat(),
        }
        try:
            with open(self.PROGRESS_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"  [Progress] Warning: Could not save progress: {e}")

    def _take_break_if_needed(self) -> bool:
        """
        Checks if typing has been active for 45-60 minutes.
        If so, takes a random 3-4 minute human rest break with a live countdown timer.
        Returns True if a break was taken.
        """
        if self.no_breaks:
            return False
        elapsed_work = time.time() - self.last_break_time
        if elapsed_work < self.next_break_interval:
            return False

        duration_sec = random.uniform(
            self.break_duration_range[0] * 60, self.break_duration_range[1] * 60
        )
        duration_min = duration_sec / 60.0
        work_mins = elapsed_work / 60.0
        resume_dt = datetime.fromtimestamp(time.time() + duration_sec).strftime('%H:%M:%S')

        print(f"\n\n{'☕ '*25}")
        print(f"  HUMAN REST BREAK")
        print(f"  Session typing time: {work_mins:.1f} minutes")
        print(f"  Taking a break for:  {duration_min:.1f} minutes ({int(duration_sec)} seconds)")
        print(f"  Resuming at:         {resume_dt}")
        print(f"{'☕ '*25}\n")

        start_break = time.time()
        while (time.time() - start_break) < duration_sec:
            if self.typer._stop_event.is_set():
                self.last_break_time = time.time()
                return True
            remaining = int(duration_sec - (time.time() - start_break))
            mins_rem = remaining // 60
            secs_rem = remaining % 60
            print(f"  Sleeping... {mins_rem:02d}:{secs_rem:02d} remaining (Press Ctrl+C to abort)  ", end='\r')
            time.sleep(1)

        print(f"\n\n  ✓ Break finished! Continuing typing...\n")

        # Reset fatigue after rest
        self.typer.reset_fatigue()

        # Re-focus target window if needed
        if self.guard:
            self.guard.ensure_focus()

        # Schedule next random 45-60 minute typing session
        self.last_break_time = time.time()
        self.next_break_interval = random.uniform(
            self.break_interval_range[0] * 60, self.break_interval_range[1] * 60
        )
        print(f"  Next break scheduled in ~{self.next_break_interval / 60.0:.1f} minutes.\n")
        return True

    def run(self, resume_from: int = 0) -> bool:
        total = len(self.files)
        if total == 0:
            print("  [ERROR] No spreadsheet files found in source folder.")
            return False

        self._create_target_structure()

        print(f"\n{'═'*65}")
        print(f"  EXCEL BATCH FOLDER REPLICATOR")
        print(f"  Source Folder:      {self.source_dir}")
        print(f"  Destination Folder: {self.target_dir}")
        print(f"  Total Files:        {total}")
        print(f"  Starting from File: #{resume_from + 1}")
        if self.stop_minutes:
            stop_dt = datetime.fromtimestamp(self.session_start + self.stop_seconds).strftime('%H:%M:%S')
            print(f"  Stop limit:         {self.stop_minutes:.1f} minutes (will stop at {stop_dt})")
        else:
            print(f"  Stop limit:         None (runs continuously)")
        if not self.no_breaks:
            first_mins = self.next_break_interval / 60.0
            first_dt = datetime.fromtimestamp(time.time() + self.next_break_interval).strftime('%H:%M:%S')
            print(f"  Breaks:             Random {self.break_duration_range[0]:.0f}-{self.break_duration_range[1]:.0f}m rest every {self.break_interval_range[0]:.0f}-{self.break_interval_range[1]:.0f}m")
            print(f"  First break in:     ~{first_mins:.1f} minutes (at {first_dt})")
        print(f"{'═'*65}\n")

        for idx in range(resume_from, total):
            if self._is_time_up() or self.typer._stop_event.is_set():
                elapsed_m = (time.time() - self.session_start) / 60.0
                if self._is_time_up():
                    print(f"\n\n{'═'*65}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Folder session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at file #{idx+1} of {total}.")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*65}\n")
                else:
                    print(f"\n[Stopped] Progress saved at file #{idx+1}")
                self._save_progress(idx, total, self.files[idx]['relative_path'] if idx < total else '', completed=False)
                break

            file_info = self.files[idx]
            rel_path = file_info['relative_path']
            abs_source = file_info['absolute_path']
            target_path = os.path.join(self.target_dir, rel_path)
            ext = file_info['extension']

            print(f"\n{'─'*65}")
            print(f"  [{idx+1}/{total}] {rel_path} ({file_info['size_bytes']} bytes)")

            if self.confirm_each:
                resp = input("  Type this spreadsheet? [Y/n/skip/quit]: ").strip().lower()
                if resp in ('n', 'skip'):
                    print("  [Skipped]")
                    continue
                elif resp in ('q', 'quit'):
                    print("  [Quit by user]")
                    break

            # Read source spreadsheet
            try:
                if ext == '.json':
                    matrix = load_matrix_from_json(abs_source)
                elif ext in ('.csv', '.tsv', '.txt'):
                    matrix = load_matrix_from_csv(
                        abs_source,
                        delimiter=self.delimiter,
                        encoding=self.encoding,
                        pad_columns=self.pad_columns,
                        strip_cells=self.strip_cells
                    )
                elif ext in ('.xlsx', '.xls'):
                    import openpyxl
                    wb = openpyxl.load_workbook(abs_source, data_only=False)
                    sheet = wb.active
                    matrix = []
                    for r in sheet.iter_rows(values_only=True):
                        matrix.append([str(v) if v is not None else "" for v in r])
                else:
                    matrix = load_matrix_from_csv(abs_source, delimiter=self.delimiter)
            except Exception as e:
                print(f"  [ERROR] Failed to load {rel_path}: {e}")
                continue

            if not matrix:
                print(f"  [Empty file — creating {target_path}]")
                launch_and_focus_excel(target_path)
                continue

            # Open target file in Excel
            had_existing = os.path.exists(target_path) and os.path.getsize(target_path) > 0
            excel_hwnd, opened_title = launch_and_focus_excel(target_path)

            # Update guard to lock onto opened workbook
            if self.guard:
                if excel_hwnd:
                    self.guard.hwnd = excel_hwnd
                    self.guard.title = opened_title
                    self.guard.pid = _window_pid(excel_hwnd)
                else:
                    self.guard.pattern = opened_title
                    if not self.guard.resolve():
                        print(f"  [FOCUS] Could not resolve Excel window.")
                        self._save_progress(idx, total, rel_path, completed=False)
                        break

                if not self.guard.ensure_focus():
                    print(f"  [FOCUS] Excel window closed. Stopping batch execution.")
                    self._save_progress(idx, total, rel_path, completed=False)
                    break

            if had_existing:
                print("  Clearing existing sheet content...")
                self.typer.clear_active_sheet()

            # Reset fatigue for new file
            self.typer.reset_fatigue()

            # Calculate remaining time for child typer
            rem_stop_min = None
            if self.stop_seconds:
                elapsed_so_far = time.time() - self.session_start
                remaining_sec = self.stop_seconds - elapsed_so_far
                if remaining_sec <= 0:
                    elapsed_m = elapsed_so_far / 60.0
                    print(f"\n\n{'═'*65}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Folder session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at file #{idx+1} of {total}.")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*65}\n")
                    self._save_progress(idx, total, rel_path, completed=False)
                    break
                rem_stop_min = max(0.1, remaining_sec / 60.0)

            # Type matrix into open Excel sheet
            file_typer = ExcelProjectTyper(
                matrix=matrix,
                profile=self.profile,
                guard=self.guard,
                nav_mode=self.nav_mode,
                save_interval=self.save_interval,
                source_name=rel_path,
                break_interval=self.break_interval_range,
                break_duration=self.break_duration_range,
                no_breaks=self.no_breaks,
                stop_minutes=rem_stop_min
            )
            # Sync break tracking so break timer accumulates across files
            file_typer.last_break_time = self.last_break_time
            file_typer.next_break_interval = self.next_break_interval

            start_t = time.time()
            success = file_typer.run(initial_delay=1.5)
            elapsed = time.time() - start_t

            # Sync back after file finishes
            self.last_break_time = file_typer.last_break_time
            self.next_break_interval = file_typer.next_break_interval

            if success:
                # Save the workbook (Ctrl+S)
                self.typer.save_workbook()
                time.sleep(random.uniform(0.5, 1.0))

                # Close workbook (Ctrl+W)
                self.typer.close_workbook()
                time.sleep(random.uniform(0.8, 1.5))

                print(f"  ✓ Completed {rel_path} in {elapsed:.1f}s")
                is_all_done = (idx == total - 1)
                self._save_progress(idx + 1 if not is_all_done else idx, total, rel_path, completed=is_all_done)

                # Check if time limit was reached during file typing
                if self._is_time_up() and not is_all_done:
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*65}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Folder session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Completed #{idx+1}. Next run starts at File #{idx + 2}.")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*65}\n")
                    break
            else:
                if self._is_time_up():
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*65}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Folder session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at file #{idx+1} of {total}: {rel_path}")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*65}\n")
                self._save_progress(idx, total, rel_path, completed=False)
                break

            # Pause between files (mental context switch)
            if idx < total - 1:
                if not self._take_break_if_needed():
                    pause = random.uniform(2.0, 4.5)
                    print(f"  Pausing {pause:.1f}s before next spreadsheet...")
                    time.sleep(pause)

        print(f"\n{'═'*65}")
        print(f"  BATCH FOLDER REPLICATION COMPLETE")
        print(f"  Total Cells Typed:  {self.typer.cells_typed}")
        print(f"  Total Chars Typed:  {self.typer.chars_typed}")
        print(f"{'═'*65}\n")
        return True


# ──────────────────────────────────────────────
#  CLI Entry Point & Arguments
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Excel Typer — High-Fidelity Human-Like Spreadsheet Automation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Folder-to-folder batch replication (all CSV/Excel files)
  python excel_typer.py --source "C:\\source_folder" --destination "C:\\dest_folder"

  # Single file source to destination
  python excel_typer.py --source "C:\\data\\sales.csv" --destination "C:\\data\\output.xlsx"

  # Dry-run preview of a folder or file
  python excel_typer.py --source "C:\\source_folder" --destination "C:\\dest_folder" --dry-run

  # Resume interrupted folder batch run
  python excel_typer.py --source "C:\\source_folder" --destination "C:\\dest_folder" --resume
        """
    )

    parser.add_argument('--source', '--file', '-s', dest='source', type=str, default=None,
                        help='Path to source data file or folder')
    parser.add_argument('--destination', '--target', '-d', dest='destination', type=str, default=None,
                        help='Path to destination file or folder to type into')
    parser.add_argument('--extensions', type=str, default=None,
                        help='Comma-separated file extensions for folder scan (default: .csv,.tsv,.xlsx,.xls,.json,.txt)')
    parser.add_argument('--skip-dirs', type=str, default=None,
                        help='Comma-separated directories to skip in folder scan (default: .git,__pycache__,node_modules,.vs,bin,obj)')
    parser.add_argument('--confirm', action='store_true',
                        help='Confirm each file before typing in folder mode')
    parser.add_argument('--sample', action='store_true',
                        help='Use built-in sample inventory dataset (no file needed)')
    parser.add_argument('--delimiter', type=str, default=None,
                        help='CSV delimiter (default: auto-detected, e.g. "," or "\\t")')
    parser.add_argument('--encoding', type=str, default=None,
                        help='File encoding (default: auto-detected from BOM/UTF-8/CP1252/Latin-1)')
    parser.add_argument('--no-pad', action='store_true',
                        help='Do not pad uneven/ragged rows with empty cells')
    parser.add_argument('--strip', action='store_true',
                        help='Trim leading and trailing whitespace from cell contents')
    parser.add_argument('--target-window', type=str, default="Excel",
                        help='Window caption pattern to lock onto (default: "Excel")')
    parser.add_argument('--target-window-exact', action='store_true',
                        help='Require exact window title match')
    parser.add_argument('--no-focus-guard', action='store_true',
                        help='Disable active window focus enforcement')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='Typing speed multiplier (0.5=slow, 1.0=normal, 2.0=fast)')
    parser.add_argument('--wpm', type=float, default=None,
                        help='Target words-per-minute (approx., overrides --speed)')
    parser.add_argument('--nav-mode', choices=['tab_enter', 'arrows'], default='tab_enter',
                        help='Navigation method between cells (default: "tab_enter")')
    parser.add_argument('--start-row', type=int, default=0,
                        help='0-based index of row to start typing from (single file mode)')
    parser.add_argument('--start-col', type=int, default=0,
                        help='0-based index of column to start typing from on the first row')
    parser.add_argument('--max-rows', type=int, default=None,
                        help='Maximum number of rows to type')
    parser.add_argument('--save-interval', type=int, default=10,
                        help='Save workbook (Ctrl+S) every N rows (0 to disable)')
    parser.add_argument('--delay', type=float, default=5.0,
                        help='Countdown seconds to focus Excel before typing starts')
    parser.add_argument('--resume', action='store_true',
                        help='Resume from last saved progress in excel_typer_progress.json (enabled by default on restart)')
    parser.add_argument('--fresh', action='store_true',
                        help='Ignore previous saved progress in excel_typer_progress.json and start from file #1 / row 1')
    parser.add_argument('--dry-run', action='store_true',
                        help='Preview rows and stats without executing keystrokes')
    parser.add_argument('--break-interval', type=str, default="45,60",
                        help='Work minutes before taking an ergonomic break (min,max) [default: 45,60]')
    parser.add_argument('--break-duration', type=str, default="3,4",
                        help='Break duration minutes (min,max) [default: 3,4]')
    parser.add_argument('--no-breaks', action='store_true',
                        help='Disable automatic rest breaks')
    parser.add_argument('--stop', type=float, default=None, metavar='MINUTES',
                        help='Stop script after working for N minutes (e.g. --stop 30). Saves progress cleanly and exits. (Default: run continuously)')

    args = parser.parse_args()

    # Speed / WPM calculation
    speed = args.speed
    if args.wpm is not None:
        speed = max(0.2, args.wpm / 40.0)

    profile = ExcelTypingProfile(speed_multiplier=speed)

    # Parse break timings (random between 45-60 min work, 3-4 min rest)
    try:
        b_interval = tuple(float(x.strip()) for x in args.break_interval.split(','))
        b_duration = tuple(float(x.strip()) for x in args.break_duration.split(','))
    except Exception:
        b_interval = (45.0, 60.0)
        b_duration = (3.0, 4.0)

    # Window Guard setup
    guard = None
    if not args.no_focus_guard and args.target_window:
        guard = WindowGuard(
            pattern=args.target_window,
            exact=args.target_window_exact,
            refocus=True
        )

    # ──────────────────────────────────────────────
    #  MODE 1: Folder-to-Folder Batch Mode
    # ──────────────────────────────────────────────
    if args.source and os.path.isdir(args.source):
        source_dir = os.path.abspath(args.source)
        dest_dir = os.path.abspath(args.destination) if args.destination else f"{source_dir}_typed"

        exts = set(x.strip().lower() for x in args.extensions.split(',')) if args.extensions else None
        skips = set(x.strip() for x in args.skip_dirs.split(',')) if args.skip_dirs else None

        scanner = SpreadsheetFolderScanner(source_dir, extensions=exts, skip_dirs=skips)
        files = scanner.scan()

        if not files:
            print(f"  [ERROR] No spreadsheet files found in folder: {source_dir}")
            sys.exit(1)

        if args.dry_run:
            print(f"\n{'═'*65}")
            print(f"  EXCEL TYPER — FOLDER DRY RUN PREVIEW")
            print(f"{'═'*65}")
            print(f"  Source Folder:      {source_dir}")
            print(f"  Destination Folder: {dest_dir}")
            print(f"  Total Files Found:  {len(files)}")
            total_bytes = sum(f['size_bytes'] for f in files)
            print(f"  Total Data Size:    {total_bytes / 1024:.1f} KB")
            print(f"\n  Files to Replicate:")
            for idx, f in enumerate(files):
                print(f"    [{idx+1}] {f['relative_path']} ({f['size_bytes']} bytes)")
            print(f"{'═'*65}\n")
            return

        resume_idx = 0
        if not args.fresh and os.path.exists(ExcelFolderReplicator.PROGRESS_FILE):
            try:
                with open(ExcelFolderReplicator.PROGRESS_FILE, 'r', encoding='utf-8') as pf:
                    pdata = json.load(pf)
                if pdata.get('mode') == 'folder':
                    same_source = os.path.normcase(os.path.normpath(pdata.get('source_dir', ''))) == os.path.normcase(os.path.normpath(source_dir))
                    if same_source:
                        is_completed = pdata.get('completed', False)
                        saved_idx = pdata.get('file_index', 0)
                        if is_completed:
                            print(f"\n  [Notice] All {pdata.get('total_files', len(files))} files in folder were completed in previous run.")
                            print(f"           Starting fresh run. (Pass --fresh to silence this notice)\n")
                        elif 0 <= saved_idx < len(files):
                            resume_idx = saved_idx
                            cur_file = pdata.get('current_file', files[resume_idx]['relative_path'])
                            print(f"\n╔{'═'*63}╗")
                            print(f"║  AUTO-RESUME ACTIVE                                           ║")
                            print(f"║  Resuming from File #{resume_idx + 1} of {len(files)}: {cur_file[:34]:<34} ║")
                            print(f"║  (To restart from File #1, pass --fresh)                      ║")
                            print(f"╚{'═'*63}╝\n")
            except Exception as e:
                print(f"  [Resume] Could not read progress ({e}), starting from beginning.")

        replicator = ExcelFolderReplicator(
            source_dir=source_dir,
            target_dir=dest_dir,
            files=files,
            profile=profile,
            guard=guard,
            nav_mode=args.nav_mode,
            save_interval=args.save_interval,
            confirm_each=args.confirm,
            break_interval=b_interval,
            break_duration=b_duration,
            no_breaks=args.no_breaks,
            delimiter=args.delimiter,
            encoding=args.encoding,
            pad_columns=not args.no_pad,
            strip_cells=args.strip,
            stop_minutes=args.stop
        )

        try:
            replicator.run(resume_from=resume_idx)
        except KeyboardInterrupt:
            print("\n\n[Aborted] Interrupted by user (Ctrl+C). Folder progress saved.")
            replicator.typer.stop()
        return

    # ──────────────────────────────────────────────
    #  MODE 2: Single-File / Sample Mode
    # ──────────────────────────────────────────────
    matrix = []
    source_name = "sample_inventory"

    if args.sample or not args.source:
        if not args.sample and not args.source:
            print("  No --source specified; defaulting to --sample dataset.\n")
        matrix = get_sample_inventory_data()
        source_name = "sample_inventory"
    else:
        source_name = os.path.basename(args.source)
        ext = os.path.splitext(args.source)[1].lower()
        if ext == '.json':
            matrix = load_matrix_from_json(args.source)
        elif ext in ('.csv', '.tsv', '.txt'):
            matrix = load_matrix_from_csv(
                args.source,
                delimiter=args.delimiter,
                encoding=args.encoding,
                pad_columns=not args.no_pad,
                strip_cells=args.strip
            )
        elif ext in ('.xlsx', '.xls'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(args.source, data_only=False)
                sheet = wb.active
                matrix = []
                for r in sheet.iter_rows(values_only=True):
                    matrix.append([str(v) if v is not None else "" for v in r])
            except ImportError:
                print("\n  [ERROR] openpyxl is not installed to read .xlsx directly.")
                print("  Fix: Either save your sheet as a CSV (e.g. data.csv), or install openpyxl:")
                print("       pip install openpyxl\n")
                sys.exit(1)
        else:
            matrix = load_matrix_from_csv(
                args.source,
                delimiter=args.delimiter,
                encoding=args.encoding,
                pad_columns=not args.no_pad,
                strip_cells=args.strip
            )

    if not matrix:
        print("  [ERROR] No data found to type.")
        sys.exit(1)

    total_chars = sum(sum(len(str(c)) for c in row) for row in matrix)
    total_cells = sum(len(row) for row in matrix)

    if args.dry_run:
        print(f"\n{'═'*65}")
        print(f"  EXCEL TYPER — DRY RUN PREVIEW")
        print(f"{'═'*65}")
        print(f"  Source:           {source_name}")
        if args.destination:
            print(f"  Destination:      {args.destination}")
        print(f"  Total Rows:       {len(matrix)}")
        print(f"  Total Columns:    {max(len(r) for r in matrix) if matrix else 0}")
        print(f"  Total Cells:      {total_cells}")
        print(f"  Total Characters: {total_chars}")
        print(f"  Estimated Time:   ~{(total_chars / 5.5 / 60):.1f} to {(total_chars / 3.0 / 60):.1f} minutes")
        print(f"\n  First 3 Rows Preview:")
        for idx, row in enumerate(matrix[:3]):
            print(f"    Row {idx+1}: {row}")
        print(f"{'═'*65}\n")
        return

    # Auto-launch Microsoft Excel and focus active sheet (Cell A1)
    excel_hwnd, opened_title = launch_and_focus_excel(args.destination)

    if guard:
        if excel_hwnd:
            guard.hwnd = excel_hwnd
            guard.title = opened_title
            guard.pid = _window_pid(excel_hwnd)
        else:
            if not guard.resolve():
                print("  [WARNING] Target window could not be locked. Proceeding with user countdown focus.")
                guard = None

    start_row = args.start_row
    if not args.fresh and start_row == 0 and os.path.exists(ExcelProjectTyper.PROGRESS_FILE):
        try:
            with open(ExcelProjectTyper.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            if progress.get('mode') != 'folder':
                same_source = progress.get('source') == source_name
                if same_source and not progress.get('completed', False):
                    saved_row = progress.get('current_row', -1)
                    if 0 <= saved_row < len(matrix) - 1:
                        start_row = saved_row + 1
                        print(f"\n╔{'═'*63}╗")
                        print(f"║  AUTO-RESUME ACTIVE                                           ║")
                        print(f"║  Resuming from Row #{start_row + 1} of {len(matrix)}: {source_name[:36]:<36} ║")
                        print(f"║  (To restart from Row #1, pass --fresh)                       ║")
                        print(f"╚{'═'*63}╝\n")
        except Exception as e:
            print(f"  [Resume] Could not read progress ({e}), starting from beginning.")
    elif args.resume and os.path.exists(ExcelProjectTyper.PROGRESS_FILE):
        try:
            with open(ExcelProjectTyper.PROGRESS_FILE, 'r', encoding='utf-8') as f:
                progress = json.load(f)
            if progress.get('mode') != 'folder':
                saved_row = progress.get('current_row', -1)
                start_row = saved_row + 1
                print(f"  [Resume] Resuming from row {start_row + 1} of {len(matrix)}")
        except Exception as e:
            print(f"  [Resume] Could not read progress ({e}), starting from beginning.")

    orchestrator = ExcelProjectTyper(
        matrix=matrix,
        profile=profile,
        guard=guard,
        nav_mode=args.nav_mode,
        save_interval=args.save_interval,
        source_name=source_name,
        break_interval=b_interval,
        break_duration=b_duration,
        no_breaks=args.no_breaks,
        stop_minutes=args.stop
    )

    try:
        orchestrator.run(
            start_row=start_row,
            start_col=args.start_col,
            max_rows=args.max_rows,
            initial_delay=args.delay
        )
    except KeyboardInterrupt:
        print("\n\n[Aborted] Interrupted by user (Ctrl+C). Progress cleanly saved.")
        orchestrator.typer.stop()


if __name__ == "__main__":
    main()
