"""
Project Typer — Human-Like Folder Replication
===============================================
Reads all source files from a SOURCE folder and re-types them
into a TARGET folder using VS Code, simulating human-like typing.

Workflow for each file:
  1. Creates the folder structure in the target directory
  2. Opens the file in VS Code via CLI (`code <filepath>`)
  3. Waits for VS Code to focus the new empty file
  4. Types the file contents character-by-character with human-like behavior
  5. Saves the file (Ctrl+S) and moves to the next file

Usage:
  python project_typer.py --source "C:\\path\\to\\source" --target "C:\\path\\to\\target"

Options:
  --source       Source folder to read files from
  --target       Target folder to type files into
  --speed        Typing speed multiplier (0.5=slow, 1.0=normal, 2.0=fast) [default: 1.0]
  --wpm          Target words-per-minute (approx., overrides --speed)
  --calibrate    Personalise timing from a typing_detector recording (JSON)
  --extensions   Comma-separated file extensions to include [default: .cs,.json,.csproj,.sln,.html,.css,.js,.md,.txt,.yml,.yaml]
  --skip-dirs    Comma-separated directory names to skip [default: bin,obj,.git,.vs,node_modules]
  --delay        Seconds to wait after opening each file in VS Code [default: 2.0]
  --dry-run      List files that would be typed without actually typing
  --resume       Resume from a specific file index (0-based)
  --confirm      Ask for confirmation before typing each file
  --break-interval  Work minutes before taking a break (min,max) [default: 45,60]
  --break-duration  Break sleep minutes (min,max) [default: 3,4]
  --no-breaks       Disable automatic rest breaks
  --target-window   Only type into a window whose title contains this string
  --target-window-exact  Require an exact title match
  --no-focus-guard  Resolve the target window but do not enforce focus

WARNING: This is for educational / research purposes only.
"""

import os
import sys
import time
import random
import math
import argparse
import threading
import json
import subprocess
from datetime import datetime

# pynput is no longer needed — all input is OS-level via ctypes SendInput
# This script requires Windows (uses user32.dll)

# ── OS-level mouse input via Windows API ──
import ctypes
import ctypes.wintypes

# Windows API constants for SendInput
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# Keyboard event flags
KEYEVENTF_SCANCODE = 0x0008      # Use hardware scan code (looks like physical keyboard)
KEYEVENTF_KEYUP = 0x0002         # Key release event
KEYEVENTF_UNICODE = 0x0004       # Unicode character input


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


def _send_mouse_input(dx, dy, mouse_data=0, flags=MOUSEEVENTF_MOVE):
    """Send a single mouse input event via Windows SendInput API (OS-level)."""
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(
        dx=dx, dy=dy, mouseData=mouse_data,
        dwFlags=flags, time=0,
        dwExtraInfo=ctypes.pointer(extra)
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _get_cursor_pos():
    """Get current cursor position via Windows API."""
    point = ctypes.wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    return point.x, point.y


def _get_screen_size():
    """Get primary monitor resolution."""
    w = ctypes.windll.user32.GetSystemMetrics(0)
    h = ctypes.windll.user32.GetSystemMetrics(1)
    return w, h


# ──────────────────────────────────────────────
#  OS-Level Keyboard Input via SendInput
# ──────────────────────────────────────────────

# Virtual key code to hardware scan code mapping
# These are the scan codes that a physical US keyboard sends
VK_TO_SCAN = {
    # Letters (Set 1 scan codes — same as physical PS/2 keyboard)
    'a': 0x1E, 'b': 0x30, 'c': 0x2E, 'd': 0x20, 'e': 0x12,
    'f': 0x21, 'g': 0x22, 'h': 0x23, 'i': 0x17, 'j': 0x24,
    'k': 0x25, 'l': 0x26, 'm': 0x32, 'n': 0x31, 'o': 0x18,
    'p': 0x19, 'q': 0x10, 'r': 0x13, 's': 0x1F, 't': 0x14,
    'u': 0x16, 'v': 0x2F, 'w': 0x11, 'x': 0x2D, 'y': 0x15,
    'z': 0x2C,
    # Number row
    '0': 0x0B, '1': 0x02, '2': 0x03, '3': 0x04, '4': 0x05,
    '5': 0x06, '6': 0x07, '7': 0x08, '8': 0x09, '9': 0x0A,
    # Symbols (unshifted)
    '-': 0x0C, '=': 0x0D, '[': 0x1A, ']': 0x1B, '\\': 0x2B,
    ';': 0x27, "'": 0x28, '`': 0x29, ',': 0x33, '.': 0x34,
    '/': 0x35, ' ': 0x39,
    # Special keys
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

# Characters that require Shift key
SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
    ':': ';', '"': "'", '~': '`', '<': ',', '>': '.',
    '?': '/',
}


def _os_key_press(scan_code: int):
    """Press a key using hardware scan code via SendInput (OS-level)."""
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(
        wVk=0, wScan=scan_code,
        dwFlags=KEYEVENTF_SCANCODE,
        time=0, dwExtraInfo=ctypes.pointer(extra)
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _os_key_release(scan_code: int):
    """Release a key using hardware scan code via SendInput (OS-level)."""
    extra = ctypes.c_ulong(0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(
        wVk=0, wScan=scan_code,
        dwFlags=KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP,
        time=0, dwExtraInfo=ctypes.pointer(extra)
    )
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))


def _os_type_unicode(char: str):
    """
    Type a Unicode character via SendInput UNICODE mode.
    Fallback for characters not in the scan code map.
    """
    extra = ctypes.c_ulong(0)
    for c in char:
        code = ord(c)
        # Key press
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki = KEYBDINPUT(
            wVk=0, wScan=code,
            dwFlags=KEYEVENTF_UNICODE,
            time=0, dwExtraInfo=ctypes.pointer(extra)
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(inp))
        # Key release
        inp2 = INPUT()
        inp2.type = INPUT_KEYBOARD
        inp2.union.ki = KEYBDINPUT(
            wVk=0, wScan=code,
            dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
            time=0, dwExtraInfo=ctypes.pointer(extra)
        )
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(inp2))


def _os_type_char_with_dwell(char: str, dwell_time: float = None):
    """
    Type a single character at the OS level with realistic key dwell time.
    Handles Shift for uppercase and symbols automatically.

    Args:
        char: The character to type
        dwell_time: How long the key stays pressed (seconds). Randomized if None.
    """
    if dwell_time is None:
        # Human dwell time: 60-150ms with some variance
        dwell_time = random.lognormvariate(math.log(0.085), 0.3)
        dwell_time = max(0.04, min(dwell_time, 0.25))

    needs_shift = False
    base_char = char

    # Check if this character needs Shift
    if char in SHIFT_MAP:
        needs_shift = True
        base_char = SHIFT_MAP[char]
    elif char.isupper():
        needs_shift = True
        base_char = char.lower()

    scan = VK_TO_SCAN.get(base_char)

    if scan is None:
        # Character not in our scan code map — use Unicode fallback
        _os_type_unicode(char)
        return

    shift_scan = VK_TO_SCAN['lshift']

    # Press Shift if needed (with slight pre-delay like a real finger)
    if needs_shift:
        _os_key_press(shift_scan)
        time.sleep(random.uniform(0.015, 0.04))  # Shift lands slightly before the key

    # Press the key
    _os_key_press(scan)

    # Hold for dwell time (realistic key press duration)
    time.sleep(dwell_time)

    # Release the key
    _os_key_release(scan)

    # Release Shift if it was pressed (slight delay after key release)
    if needs_shift:
        time.sleep(random.uniform(0.01, 0.03))
        _os_key_release(shift_scan)


def _os_press_special(key_name: str, dwell_time: float = None):
    """
    Press and release a special key (Enter, Tab, Backspace, etc.)
    at the OS level with realistic dwell time.
    """
    if dwell_time is None:
        dwell_time = random.uniform(0.05, 0.12)

    scan = VK_TO_SCAN.get(key_name)
    if scan is None:
        return

    _os_key_press(scan)
    time.sleep(dwell_time)
    _os_key_release(scan)


def _os_hotkey(modifier: str, key_char: str):
    """
    Press a keyboard shortcut (e.g., Ctrl+S) at the OS level.
    Simulates the natural timing of holding modifier then pressing key.
    """
    mod_scan = VK_TO_SCAN.get(modifier)
    key_scan = VK_TO_SCAN.get(key_char)
    if not mod_scan or not key_scan:
        return

    # Press modifier
    _os_key_press(mod_scan)
    time.sleep(random.uniform(0.03, 0.07))  # Human delay between modifier and key

    # Press and release the key
    _os_key_press(key_scan)
    time.sleep(random.uniform(0.05, 0.10))
    _os_key_release(key_scan)

    # Release modifier
    time.sleep(random.uniform(0.02, 0.05))
    _os_key_release(mod_scan)


# ──────────────────────────────────────────────
#  Window targeting / focus safety
# ──────────────────────────────────────────────
#  SendInput goes to whatever window currently has focus — the typer itself
#  has no idea where the text lands. A notification, an alt-tab, or a slow
#  VS Code load is enough to dump hundreds of lines into the wrong app.
#  These helpers let the typer pin itself to one window and abort instead of
#  typing blind.

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TokenElevation = 20

_user32 = ctypes.windll.user32
_kernel32 = ctypes.windll.kernel32
_advapi32 = ctypes.windll.advapi32

# 64-bit handles must not be truncated to c_int (ctypes' default restype)
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
_advapi32.OpenProcessToken.restype = ctypes.wintypes.BOOL
_advapi32.OpenProcessToken.argtypes = [
    ctypes.wintypes.HANDLE, ctypes.wintypes.DWORD,
    ctypes.POINTER(ctypes.wintypes.HANDLE)
]
_advapi32.GetTokenInformation.restype = ctypes.wintypes.BOOL

WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)


def _safe_text(text: str) -> str:
    """
    Make an arbitrary window title safe to print.

    Titles come from other applications and may contain zero-width or other
    non-ASCII characters the console code page cannot encode. Printing one
    unguarded raises UnicodeEncodeError in the middle of a run.
    """
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors='replace').decode(
            encoding, errors='replace')


def _window_title(hwnd) -> str:
    """Return the caption of a window ('' if it has none)."""
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ''
    buf = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def _window_class(hwnd) -> str:
    """Return the Win32 class name of a window."""
    buf = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _window_pid(hwnd) -> int:
    """Return the PID that owns a window."""
    pid = ctypes.wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _window_thread_id(hwnd) -> int:
    """Return the UI thread id that owns a window."""
    pid = ctypes.wintypes.DWORD()
    return _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))


def _get_foreground_window():
    """Return the window that currently has keyboard focus."""
    return _user32.GetForegroundWindow()


def _list_windows() -> list:
    """List visible top-level windows that have a title."""
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


def find_windows(pattern: str, exact: bool = False) -> list:
    """
    Find visible windows whose title matches `pattern`.

    Substring match is case-insensitive by default, which is what you want for
    `--target-window "Visual Studio Code"` (the real title has the folder name
    appended). Pass exact=True to require a full match.
    """
    if not pattern:
        return []
    if exact:
        return [w for w in _list_windows() if w['title'] == pattern]
    needle = pattern.casefold()
    return [w for w in _list_windows() if needle in w['title'].casefold()]


def _focus_window(hwnd) -> bool:
    """
    Bring `hwnd` to the foreground and verify it actually took focus.

    SetForegroundWindow is refused when the calling thread does not own the
    foreground window (the "foreground lock"). Attaching to the foreground
    thread's input queue lifts that restriction for the duration of the call.
    """
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
    """True if the process runs with an elevated (admin) token."""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        token = ctypes.wintypes.HANDLE()
        if not _advapi32.OpenProcessToken(
                handle, TOKEN_QUERY, ctypes.byref(token)):
            return False
        try:
            elevation = ctypes.wintypes.DWORD()
            size = ctypes.wintypes.DWORD()
            if not _advapi32.GetTokenInformation(
                    token, TokenElevation,
                    ctypes.byref(elevation), ctypes.sizeof(elevation),
                    ctypes.byref(size)):
                return False
            return bool(elevation.value)
        finally:
            _kernel32.CloseHandle(token)
    finally:
        _kernel32.CloseHandle(handle)


def _is_self_elevated() -> bool:
    """True if this Python process runs elevated."""
    return _is_process_elevated(os.getpid())


class WindowGuard:
    """
    Pins the typer to one specific window and refuses to type anywhere else.

    Three jobs:
      1. resolve()      — find the window once, up front, and fail loudly if the
                          title matches nothing or is ambiguous
      2. ensure_focus() — before each file, make sure the target is foreground
      3. check()        — polled mid-file; if focus was stolen, re-focus once and
                          abort the file rather than typing into the wrong app
    """

    def __init__(self, pattern: str, exact: bool = False,
                 refocus: bool = True):
        self.pattern = pattern
        self.exact = exact
        self.refocus = refocus
        self.hwnd = None
        self.title = ''
        self.pid = 0
        self.refocus_events = 0

    # ── discovery ──
    def resolve(self) -> bool:
        """Locate the target window. Returns False if unusable."""
        matches = find_windows(self.pattern, exact=self.exact)

        if not matches:
            print(f"\n  [FOCUS] No visible window matches --target-window "
                  f"{self.pattern!r}")
            self._print_candidates()
            return False

        if len(matches) > 1:
            fg = _get_foreground_window()
            chosen = next(
                (w for w in matches if w['hwnd'] == fg), matches[0]
            )
            print(f"\n  [FOCUS] {len(matches)} windows match "
                  f"{self.pattern!r} — using the "
                  f"{'focused' if chosen['hwnd'] == fg else 'first'} one:")
            for w in matches:
                mark = '→' if w['hwnd'] == chosen['hwnd'] else ' '
                print(f"    {mark} {_safe_text(w['title'])}")
            print(f"      Narrow the pattern if this is not the right window.")
        else:
            chosen = matches[0]

        self.hwnd = chosen['hwnd']
        self.title = chosen['title']
        self.pid = chosen['pid']

        if not _user32.IsWindow(self.hwnd):
            print(f"  [FOCUS] Target window vanished before typing started.")
            return False

        print(f"  [FOCUS] Locked onto: {_safe_text(self.title)}")
        print(f"          class={chosen['class']}  pid={self.pid}")

        # Elevation mismatch makes SendInput fail silently — catch it now
        # rather than after the first keystroke goes nowhere.
        if _is_process_elevated(self.pid) and not _is_self_elevated():
            print("\n  [FOCUS] ERROR: the target window runs elevated (admin) "
                  "but this script does not.")
            print("          Windows blocks SendInput from a normal process to "
                  "an elevated window.")
            print("          Fix: run this script as Administrator too, or "
                  "target a non-elevated window.")
            return False

        return True

    def _print_candidates(self):
        """Show a few real window titles so the user can copy a correct one."""
        candidates = [w for w in _list_windows() if w['title'].strip()]
        if not candidates:
            return
        print("          Visible windows right now:")
        for w in candidates[:15]:
            print(f"            - {_safe_text(w['title'])}")
        if len(candidates) > 15:
            print(f"            ... and {len(candidates) - 15} more")

    # ── focus enforcement ──
    def alive(self) -> bool:
        return self.hwnd is not None and bool(_user32.IsWindow(self.hwnd))

    def ensure_focus(self, attempts: int = 3) -> bool:
        """Make the target window foreground. Returns True when confirmed."""
        if not self.alive():
            print("  [FOCUS] Target window is gone (closed or crashed).")
            return False
        if _get_foreground_window() == self.hwnd:
            return True
        if not self.refocus:
            # Guard disabled (--no-focus-guard): the window was still resolved
            # and elevation-checked up front, but focus is not enforced.
            return True

        for attempt in range(attempts):
            _focus_window(self.hwnd)
            time.sleep(0.15 + attempt * 0.10)
            if _get_foreground_window() == self.hwnd:
                if attempt:
                    self.refocus_events += 1
                return True

        print(f"  [FOCUS] Could not focus {_safe_text(self.title)!r}. "
              f"Click it once, then let the run continue.")
        return False

    def check(self) -> bool:
        """
        Polled while typing. Returns False to abort the current file.

        A single stolen-focus event is re-focused; if it happens again the file
        is abandoned so text cannot spray into another application.
        """
        if _get_foreground_window() == self.hwnd:
            return True

        if not self.refocus:
            return True  # guard disabled for focus, keep typing

        # Focus moved — try to take it back once, then give up.
        if _focus_window(self.hwnd):
            self.refocus_events += 1
            print("\n  [FOCUS] Focus was stolen — target window refocused.")
            return True

        print("\n  [FOCUS] ABORT: focus left the target window and could not "
              "be restored.")
        print("          Stopping this file to avoid typing into the wrong "
              "application.")
        return False

    def summary(self) -> str:
        if self.hwnd is None:
            return "no target window"
        return f"{_safe_text(self.title)!r} ({self.refocus_events} refocus events)"


# ──────────────────────────────────────────────
#  Human Mouse Simulator (OS-level via SendInput)
# ──────────────────────────────────────────────

class HumanMouseSimulator:
    """
    Simulates realistic human mouse movements at the OS level
    using Windows SendInput API (bypasses pynput abstraction).

    Movement types:
      - Bezier curve paths with variable speed
      - Idle drift (hand resting on mouse)
      - Scroll wheel (reading code)
      - Move to screen regions (editor, scrollbar, tabs)
      - Micro-tremor (physiological hand shake)
    """

    def __init__(self):
        self.screen_w, self.screen_h = _get_screen_size()
        # Define VS Code editor regions (approximate, will adapt to screen)
        self._compute_regions()

    def _compute_regions(self):
        """Compute approximate VS Code UI regions based on screen size."""
        w, h = self.screen_w, self.screen_h
        self.regions = {
            # Main editor text area (center of screen)
            'editor': (int(w * 0.15), int(h * 0.08), int(w * 0.85), int(h * 0.90)),
            # Tab bar at the top
            'tabs': (int(w * 0.15), int(h * 0.02), int(w * 0.85), int(h * 0.06)),
            # Scrollbar on the right edge
            'scrollbar': (int(w * 0.87), int(h * 0.08), int(w * 0.90), int(h * 0.90)),
            # Line numbers gutter
            'gutter': (int(w * 0.12), int(h * 0.08), int(w * 0.15), int(h * 0.90)),
            # File explorer sidebar
            'sidebar': (int(w * 0.0), int(h * 0.08), int(w * 0.12), int(h * 0.90)),
        }

    def _bezier_point(self, t: float, p0, p1, p2, p3) -> tuple:
        """
        Compute a point on a cubic Bezier curve at parameter t.
        This creates natural arced paths instead of straight lines.
        """
        u = 1 - t
        x = (u**3 * p0[0] + 3 * u**2 * t * p1[0] +
             3 * u * t**2 * p2[0] + t**3 * p3[0])
        y = (u**3 * p0[1] + 3 * u**2 * t * p1[1] +
             3 * u * t**2 * p2[1] + t**3 * p3[1])
        return int(x), int(y)

    def _generate_control_points(self, start, end) -> tuple:
        """
        Generate two random control points for a Bezier curve
        that creates a natural-looking arc between start and end.
        """
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        dist = math.sqrt(dx**2 + dy**2)

        # Control points offset perpendicular to the line, proportional to distance
        offset = dist * random.uniform(0.1, 0.4)
        angle = math.atan2(dy, dx)
        perp = angle + math.pi / 2 * random.choice([-1, 1])

        mid_x = (start[0] + end[0]) / 2
        mid_y = (start[1] + end[1]) / 2

        # First control point — biased toward start
        cp1 = (
            start[0] + dx * random.uniform(0.2, 0.4) + math.cos(perp) * offset * random.uniform(0.3, 1.0),
            start[1] + dy * random.uniform(0.2, 0.4) + math.sin(perp) * offset * random.uniform(0.3, 1.0),
        )
        # Second control point — biased toward end
        cp2 = (
            start[0] + dx * random.uniform(0.6, 0.8) + math.cos(perp) * offset * random.uniform(-0.5, 0.5),
            start[1] + dy * random.uniform(0.6, 0.8) + math.sin(perp) * offset * random.uniform(-0.5, 0.5),
        )
        return cp1, cp2

    def _ease_in_out(self, t: float) -> float:
        """
        Ease-in-out timing function — starts slow, speeds up,
        then slows down at the end. Mimics human motor control.
        """
        if t < 0.5:
            return 4 * t * t * t
        else:
            return 1 - (-2 * t + 2) ** 3 / 2

    def move_to(self, target_x: int, target_y: int, duration: float = None):
        """
        Move the mouse cursor to (target_x, target_y) along a natural
        Bezier curve path with variable speed (OS-level SendInput).

        Args:
            target_x, target_y: Destination pixel coordinates
            duration: Total movement time in seconds (auto-calculated if None)
        """
        start_x, start_y = _get_cursor_pos()
        dist = math.sqrt((target_x - start_x)**2 + (target_y - start_y)**2)

        if dist < 3:
            return  # Already there

        # Auto-calculate duration based on Fitts's Law approximation
        if duration is None:
            duration = 0.2 + dist / 2000.0 + random.uniform(0.05, 0.15)
            duration = min(duration, 1.5)  # Cap at 1.5 seconds

        # Generate Bezier control points for a natural arc
        cp1, cp2 = self._generate_control_points(
            (start_x, start_y), (target_x, target_y)
        )

        # Number of steps — more steps for longer distances
        steps = max(15, int(dist / 5))
        steps = min(steps, 120)  # Cap steps

        # Convert target to absolute coordinates for SendInput
        # SendInput ABSOLUTE uses 0-65535 range
        abs_factor_x = 65535 / self.screen_w
        abs_factor_y = 65535 / self.screen_h

        for step in range(1, steps + 1):
            t = step / steps
            # Apply ease-in-out for natural acceleration/deceleration
            eased_t = self._ease_in_out(t)

            # Get point on Bezier curve
            bx, by = self._bezier_point(
                eased_t,
                (start_x, start_y), cp1, cp2, (target_x, target_y)
            )

            # Add micro-tremor (tiny physiological hand shake)
            if step < steps:  # No tremor on final position
                tremor = 1 + int(dist / 500)  # More tremor for longer moves
                bx += random.randint(-tremor, tremor)
                by += random.randint(-tremor, tremor)

            # Clamp to screen
            bx = max(0, min(bx, self.screen_w - 1))
            by = max(0, min(by, self.screen_h - 1))

            # Send absolute mouse movement via OS API
            abs_x = int(bx * abs_factor_x)
            abs_y = int(by * abs_factor_y)
            _send_mouse_input(
                abs_x, abs_y, 0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            )

            # Variable sleep per step (ease-in-out affects timing too)
            step_delay = duration / steps
            # Add jitter to step timing
            step_delay *= random.uniform(0.7, 1.3)
            time.sleep(step_delay)

    def idle_drift(self):
        """
        Simulate subtle idle mouse drift — the kind that happens
        when your hand rests on the mouse while typing.
        Small, slow, random movement over 0.3-0.8 seconds.
        """
        cx, cy = _get_cursor_pos()
        # Small drift: 2-15 pixels in a random direction
        drift_dist = random.uniform(2, 15)
        angle = random.uniform(0, 2 * math.pi)
        target_x = int(cx + drift_dist * math.cos(angle))
        target_y = int(cy + drift_dist * math.sin(angle))

        # Clamp to screen
        target_x = max(0, min(target_x, self.screen_w - 1))
        target_y = max(0, min(target_y, self.screen_h - 1))

        duration = random.uniform(0.15, 0.5)
        steps = random.randint(5, 12)

        abs_fx = 65535 / self.screen_w
        abs_fy = 65535 / self.screen_h

        for s in range(1, steps + 1):
            t = s / steps
            ix = int(cx + (target_x - cx) * t + random.randint(-1, 1))
            iy = int(cy + (target_y - cy) * t + random.randint(-1, 1))
            ix = max(0, min(ix, self.screen_w - 1))
            iy = max(0, min(iy, self.screen_h - 1))
            _send_mouse_input(
                int(ix * abs_fx), int(iy * abs_fy), 0,
                MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
            )
            time.sleep(duration / steps)

    def scroll(self, lines: int = None):
        """
        Simulate mouse scroll wheel (reading/reviewing code).
        Uses OS-level SendInput for the scroll event.

        Args:
            lines: Number of lines to scroll (negative=down, positive=up).
                   Auto-randomized if None.
        """
        if lines is None:
            lines = random.choice([-3, -2, -1, 1, 2, 3, -4, -5])

        # WHEEL_DELTA is 120 per notch
        wheel_delta = lines * 120
        _send_mouse_input(0, 0, wheel_delta & 0xFFFFFFFF, MOUSEEVENTF_WHEEL)
        time.sleep(random.uniform(0.1, 0.3))

    def move_to_region(self, region_name: str):
        """
        Move cursor to a random point within a named VS Code region.
        Simulates looking at tabs, scrollbar, line numbers, etc.
        """
        if region_name not in self.regions:
            return
        x1, y1, x2, y2 = self.regions[region_name]
        target_x = random.randint(x1, x2)
        target_y = random.randint(y1, y2)
        self.move_to(target_x, target_y)

    def move_to_editor(self):
        """
        Move cursor back to a random position in the editor text area.
        Called after visiting scrollbar/tabs/etc.
        """
        self.move_to_region('editor')

    def do_random_human_action(self):
        """
        Perform a random mouse action that a human would naturally do
        while coding. Weighted by how frequently each action occurs.
        """
        action = random.choices(
            ['drift', 'scroll_down', 'scroll_up', 'glance_tabs',
             'glance_scrollbar', 'glance_gutter', 'move_in_editor'],
            weights=[35, 15, 8, 8, 7, 7, 20],
            k=1
        )[0]

        if action == 'drift':
            self.idle_drift()

        elif action == 'scroll_down':
            self.scroll(random.randint(-4, -1))

        elif action == 'scroll_up':
            self.scroll(random.randint(1, 3))

        elif action == 'glance_tabs':
            self.move_to_region('tabs')
            time.sleep(random.uniform(0.3, 1.0))  # "Reading" the tab name
            self.move_to_editor()  # Back to editor

        elif action == 'glance_scrollbar':
            self.move_to_region('scrollbar')
            time.sleep(random.uniform(0.2, 0.6))
            self.move_to_editor()

        elif action == 'glance_gutter':
            self.move_to_region('gutter')
            time.sleep(random.uniform(0.2, 0.5))
            self.move_to_editor()

        elif action == 'move_in_editor':
            self.move_to_region('editor')



# ──────────────────────────────────────────────
#  Human Motor Model Constants
# ──────────────────────────────────────────────

# Finger used for each key (0 = left pinky ... 7 = right pinky).
# Used to model same-finger and same-hand bigram penalties.
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

# Per-key difficulty multiplier: pinky/ring and far reaches are slower.
KEY_DIFFICULTY = {
    'q': 1.30, 'z': 1.35, 'p': 1.15, 'x': 1.12,
    '/': 1.22, ';': 1.10, "'": 1.10, '-': 1.10,
    '=': 1.10, '[': 1.10, ']': 1.10, '\\': 1.16, '`': 1.15,
    ',': 1.05, '.': 1.05,
}

# Per-key dwell bias: weak fingers hold keys slightly longer.
KEY_DWELL_BIAS = {
    'q': 1.22, 'z': 1.28, 'p': 1.12, 'x': 1.10,
    '/': 1.16, ';': 1.08, "'": 1.08, '-': 1.06,
    '=': 1.06, '[': 1.06, ']': 1.06, '\\': 1.10, '`': 1.10,
}


# ──────────────────────────────────────────────
#  Typing Profile (same engine as human_typer.py)
# ──────────────────────────────────────────────

class TypingProfile:
    """Configurable profile that controls how 'human' the typing looks."""

    def __init__(self, speed_multiplier: float = 1.0):
        self.speed_multiplier = speed_multiplier

        # Base inter-key delay range (seconds) — adjusted by speed multiplier
        self.base_delay_min = 0.04 / speed_multiplier
        self.base_delay_max = 0.14 / speed_multiplier

        # ── Key press dwell time (how long a key is held down) ──
        self.dwell_mean = 0.085
        self.dwell_sigma = 0.30

        # ── Typo model ──
        # Human errors are not all "wrong neighbour key". Real typists also
        # double a letter, insert an extra key, drop a key, or swap two keys.
        self.typo_probability = 0.06
        self.typo_type_weights = {
            'substitution': 0.48,   # hit a neighbouring key
            'doubling': 0.18,       # same key twice
            'insertion': 0.12,      # extra key before the real one
            'omission': 0.11,       # skip a character, then notice
            'transposition': 0.11,  # swap two adjacent characters
        }
        self.typo_notice_delay = (0.08, 0.35)     # time to realise the mistake
        self.typo_retype_delay = (0.04, 0.14)      # speed of corrective retype

        # ── Warm-up and macro rhythm drift ──
        # Typists start a little slower, then settle, and their speed wanders
        # slowly over a long session (attention, mood, comfort).
        self.warmup_chars = 150
        self.warmup_multiplier = 1.45
        self.rhythm_drift_interval = 60
        self.rhythm_drift_sigma = 0.10
        self.rhythm_offset_min = 0.78
        self.rhythm_offset_max = 1.30

        # ── Occasional distractions (phone, someone talking, ...) ──
        self.distraction_probability = 0.0006
        self.distraction_duration = (3.0, 12.0)

        # ── Reading / code-structure pauses ──
        self.pause_after_file_start = (0.4, 1.5)
        self.pause_before_comment_prob = 0.35
        self.pause_before_comment = (0.15, 0.7)
        self.pause_after_line_start = (0.02, 0.09)

        # Thinking and cognitive pauses (all randomized ranges)
        self.pause_after_word = (0.05 / speed_multiplier, 0.20 / speed_multiplier)   # Pause after completing each word
        self.pause_word_thinking_prob = 0.15                                        # Chance of slightly longer word pause
        self.pause_word_thinking = (0.18 / speed_multiplier, 0.45 / speed_multiplier)
        self.pause_after_newline = (0.2 / speed_multiplier, 1.2 / speed_multiplier)
        self.pause_after_period = (0.15 / speed_multiplier, 0.5 / speed_multiplier)
        self.pause_after_brace = (0.1 / speed_multiplier, 0.6 / speed_multiplier)   # Pause after { } blocks
        self.pause_thinking_probability = 0.015
        self.pause_thinking_duration = (0.5, 2.0)

        # Long pauses between logical blocks (function definitions, classes)
        self.pause_between_blocks = (1.0, 4.0)

        # Burst typing for common tokens
        self.burst_tokens_csharp = [
            "public ", "private ", "protected ", "static ",
            "class ", "namespace ", "using ", "return ",
            "void ", "string ", "int ", "bool ", "var ",
            "async ", "await ", "Task", "new ", "this.",
            "null", "true", "false", "readonly ",
            "interface ", "override ", "virtual ",
            "get;", "set;", "get; set;",
            "[HttpGet]", "[HttpPost]", "[HttpPut]", "[HttpDelete]",
            "[ApiController]", "[Route(",
            "ILogger", "IConfiguration",
            "    ",   # 4-space indent
            "        ",  # 8-space indent
        ]
        self.burst_tokens_general = [
            "function ", "const ", "let ", "var ",
            "import ", "export ", "from ", "require(",
            "def ", "self.", "print(", "return ",
            "if ", "else ", "elif ", "for ", "while ",
            "true", "false", "null", "undefined",
            "    ",
        ]
        self.burst_speed_multiplier = 0.4

        # Fatigue model
        self.fatigue_onset_chars = 500
        self.fatigue_slowdown_factor = 0.01
        self.fatigue_typo_multiplier = 2.0   # fatigue makes more mistakes
        self.fatigue_pause_multiplier = 1.4  # and longer hesitations
        self.fatigue_reset_on_new_file = True

        # Mouse behavior (OS-level)
        self.mouse_action_probability = 0.04     # 4% chance per keystroke
        self.mouse_drift_probability = 0.06      # 6% chance of idle drift
        self.mouse_scroll_probability = 0.008    # 0.8% chance of scrolling
        self.mouse_glance_probability = 0.005    # 0.5% chance of glancing at UI
        self.mouse_jitter_range = (-4, 4)        # Legacy fallback range

        # Keyboard neighbors for realistic typo generation
        self.key_neighbors = {
            'a': 'sqwz', 'b': 'vghn', 'c': 'xdfv', 'd': 'serfcx',
            'e': 'wsdfr', 'f': 'drtgvc', 'g': 'ftyhbv', 'h': 'gyujnb',
            'i': 'ujkol', 'j': 'huiknm', 'k': 'jiolm', 'l': 'kop',
            'm': 'njk', 'n': 'bhjm', 'o': 'iklp', 'p': 'ol',
            'q': 'wa', 'r': 'edft', 's': 'awedxz', 't': 'rfgy',
            'u': 'yhjki', 'v': 'cfgb', 'w': 'qase', 'x': 'zsdc',
            'y': 'tghu', 'z': 'asx',
        }

        self.slow_digraphs = {
            'zx', 'xz', 'qp', 'pq', 'zq', 'qz',
            'bf', 'fb', 'gn', 'ng', 'mj', 'jm',
        }
        self.fast_digraphs = {
            'th', 'he', 'in', 'er', 'an', 'en', 'on', 'at',
            'es', 'ed', 'te', 'ti', 'or', 'st', 'ar', 'nd',
            'to', 'nt', 'is', 'of', 'it', 'al', 'as', 'ha',
            'se', 'ou', 're', 'ne', 'ea', 'ri', 'de', 'le',
        }


def calibrate_profile_from_recording(profile: TypingProfile,
                                     recording: dict,
                                     min_samples: int = 20) -> dict:
    """
    Adjust a TypingProfile using a real keystroke recording
    (the JSON format produced by typing_detector.py). This personalises the
    typer's rhythm, dwell time and error rate to the recorded human.
    """
    events = recording.get('keyboard_events', [])
    presses = [e for e in events if e.get('event') == 'press']
    if len(presses) < min_samples:
        raise ValueError(
            f"Need at least {min_samples} key presses, got {len(presses)}"
        )

    intervals = []
    for a, b in zip(presses, presses[1:]):
        dt = b['timestamp'] - a['timestamp']
        if 0 < dt < 5.0:  # ignore window-switch gaps
            intervals.append(dt)
    if not intervals:
        raise ValueError("No usable inter-key intervals in recording")

    dwell_times = []
    pending = {}
    for event in events:
        key = event.get('key')
        if event.get('event') == 'press':
            pending[key] = event['timestamp']
        elif event.get('event') == 'release' and key in pending:
            dwell = event['timestamp'] - pending.pop(key)
            if 0 < dwell < 0.6:
                dwell_times.append(dwell)

    def percentile(values, q):
        values = sorted(values)
        if not values:
            return None
        pos = (len(values) - 1) * q
        lo, hi = int(math.floor(pos)), int(math.ceil(pos))
        if lo == hi:
            return values[lo]
        return values[lo] * (hi - pos) + values[hi] * (pos - lo)

    p10 = percentile(intervals, 0.10)
    p50 = percentile(intervals, 0.50)
    p90 = percentile(intervals, 0.90)
    mean_iki = sum(intervals) / len(intervals)

    profile.base_delay_min = max(0.02, min(p10, 0.25))
    profile.base_delay_max = max(profile.base_delay_min + 0.01,
                                 min(p90, 0.60))

    if dwell_times:
        dwell_mean = sum(dwell_times) / len(dwell_times)
        profile.dwell_mean = max(0.03, min(dwell_mean, 0.25))
        dwell_var = sum((d - dwell_mean) ** 2 for d in dwell_times) / len(dwell_times)
        dwell_std = math.sqrt(dwell_var)
        profile.dwell_sigma = max(
            0.15, min(dwell_std / dwell_mean if dwell_mean else 0.3, 0.50)
        )

    backspaces = sum(
        1 for e in presses if 'backspace' in str(e.get('key', '')).lower()
    )
    backspace_ratio = backspaces / len(presses)
    if backspace_ratio > 0:
        profile.typo_probability = max(0.005, min(0.09, backspace_ratio * 1.2))

    long_pauses = sorted(x for x in intervals if x >= 0.5)
    if long_pauses:
        profile.pause_after_newline = (
            max(0.05, percentile(long_pauses, 0.25)),
            max(0.10, percentile(long_pauses, 0.75)),
        )

    return {
        'samples': len(intervals),
        'mean_iki_ms': mean_iki * 1000,
        'p10_ms': p10 * 1000,
        'p50_ms': p50 * 1000,
        'p90_ms': p90 * 1000,
        'dwell_samples': len(dwell_times),
        'dwell_mean_ms': (profile.dwell_mean * 1000 if dwell_times else None),
        'backspace_ratio': backspace_ratio,
        'typo_probability': profile.typo_probability,
    }


# ──────────────────────────────────────────────
#  Human Typer Engine (enhanced for project use)
# ──────────────────────────────────────────────

class HumanTyper:
    """Types text with human-like behavior using OS-level keyboard input."""

    def __init__(self, profile: TypingProfile = None):
        self.profile = profile or TypingProfile()
        self.mouse_sim = HumanMouseSimulator()  # OS-level mouse control
        self.chars_typed = 0
        self._stop_event = threading.Event()
        # Optional callback (set by ProjectTyper) that is polled while typing so
        # long files still get rest breaks every 30-60 minutes.
        self._periodic_callback = None
        # Optional focus guard (WindowGuard.check). Polled every few characters
        # so a stolen focus aborts the file instead of typing into another app.
        self._focus_check = None
        self._focus_check_interval = 20
        self._next_focus_check = 0
        # Slow-moving session rhythm (attention / comfort drift)
        self._rhythm_offset = 1.0
        self._next_rhythm_drift = random.randint(
            max(20, self.profile.rhythm_drift_interval // 2),
            self.profile.rhythm_drift_interval * 3 // 2,
        )

    def stop(self):
        self._stop_event.set()

    def reset_fatigue(self):
        """Reset the fatigue/warm-up counters (called between files)."""
        if self.profile.fatigue_reset_on_new_file:
            self.chars_typed = 0
            self._rhythm_offset = 1.0
            self._next_rhythm_drift = random.randint(
                max(20, self.profile.rhythm_drift_interval // 2),
                self.profile.rhythm_drift_interval * 3 // 2,
            )

    # ── Motor / cognitive state helpers ──

    def _fatigue_factor(self) -> float:
        """0.0 before fatigue starts, growing afterwards (1.0 = +100 chars)."""
        p = self.profile
        if self.chars_typed <= p.fatigue_onset_chars:
            return 0.0
        return (self.chars_typed - p.fatigue_onset_chars) / 100.0

    def _warmup_factor(self) -> float:
        """Extra delay at the start of a file that fades over warmup_chars."""
        p = self.profile
        if self.chars_typed >= p.warmup_chars:
            return 1.0
        remaining = 1.0 - (self.chars_typed / max(1, p.warmup_chars))
        return 1.0 + (p.warmup_multiplier - 1.0) * (remaining ** 2)

    def _update_rhythm_drift(self):
        """Random-walk the overall typing speed to mimic attention drift."""
        p = self.profile
        if self.chars_typed >= self._next_rhythm_drift:
            self._rhythm_offset *= random.lognormvariate(0.0, p.rhythm_drift_sigma)
            self._rhythm_offset = max(
                p.rhythm_offset_min, min(self._rhythm_offset, p.rhythm_offset_max)
            )
            self._next_rhythm_drift = self.chars_typed + random.randint(
                max(20, p.rhythm_drift_interval // 2),
                p.rhythm_drift_interval * 3 // 2,
            )

    def _sample_dwell(self, char: str) -> float:
        """Sample a realistic key-hold time for a single character."""
        p = self.profile
        dwell = random.lognormvariate(
            math.log(max(0.02, p.dwell_mean)),
            p.dwell_sigma * random.uniform(0.85, 1.15),
        )
        dwell *= KEY_DWELL_BIAS.get(char.lower(), 1.0)
        dwell *= 1.0 + (self._warmup_factor() - 1.0) * 0.25
        dwell *= 1.0 + self._fatigue_factor() * 0.004
        return max(0.035, min(dwell, 0.28))

    def _get_inter_key_delay(self, prev_char: str, curr_char: str) -> float:
        """
        Flight time between two keystrokes. Models:
          - log-normal base distribution (right-skewed like real typists)
          - common vs awkward digraphs
          - same-finger / same-hand bigram penalties, hand alternation bonus
          - per-key difficulty (pinky, number row, far reaches)
          - Shift and symbol overhead
          - warm-up, slow rhythm drift, fatigue
          - Gaussian micro-jitter so no two delays are ever identical
        """
        p = self.profile
        self._update_rhythm_drift()

        base = random.lognormvariate(
            math.log((p.base_delay_min + p.base_delay_max) / 2),
            random.uniform(0.30, 0.40)
        )
        base = max(p.base_delay_min * random.uniform(0.85, 1.05),
                   min(base, p.base_delay_max * random.uniform(1.8, 2.2)))

        digraph = (prev_char + curr_char).lower()
        if digraph in p.fast_digraphs:
            base *= random.uniform(0.55, 0.70)
        elif digraph in p.slow_digraphs:
            base *= random.uniform(1.35, 1.65)

        prev_base = prev_char.lower() if len(prev_char) == 1 else ''
        curr_base = curr_char.lower() if len(curr_char) == 1 else ''

        # Same-finger / same-hand / alternating-hand model
        prev_finger = KEY_FINGER.get(prev_base)
        curr_finger = KEY_FINGER.get(curr_base)
        if prev_finger is not None and curr_finger is not None:
            if prev_finger == curr_finger:
                base *= random.uniform(1.18, 1.45)      # same finger: slow
            elif (prev_finger < 4) == (curr_finger < 4):
                base *= random.uniform(1.03, 1.12)      # same hand: slightly slower
            else:
                base *= random.uniform(0.86, 0.97)      # hand alternation: faster

        # Per-key difficulty
        base *= KEY_DIFFICULTY.get(curr_base, 1.0)

        if curr_char.isdigit():
            base *= random.uniform(1.05, 1.20)

        if curr_char.isupper() or curr_char in '!@#$%^&*()_+{}|:"<>?~':
            base += random.uniform(0.02, 0.065)

        # Warm-up and long-session rhythm drift
        base *= self._warmup_factor()
        base *= self._rhythm_offset

        # Fatigue
        fatigue = self._fatigue_factor()
        if fatigue > 0:
            base *= 1.0 + fatigue * p.fatigue_slowdown_factor * random.uniform(0.8, 1.2)

        # Add Gaussian micro-jitter to guarantee no two delays are ever identical
        jitter = random.gauss(0, 0.006)
        base = max(0.015, base + jitter)

        return base

    def _neighbor_typo(self, char: str) -> str:
        """Pick a physically adjacent key as the mistaken character."""
        neighbors = self.profile.key_neighbors.get(char.lower(), '')
        if not neighbors:
            return None
        typo = random.choice(neighbors)
        return typo.upper() if char.isupper() else typo

    def _typo_probability_now(self) -> float:
        """Typo rate rises with fatigue."""
        p = self.profile
        prob = p.typo_probability
        fatigue = self._fatigue_factor()
        if fatigue > 0:
            prob *= 1.0 + min(fatigue, 5.0) * p.fatigue_typo_multiplier
        return min(prob, 0.12)

    def _choose_typo_type(self) -> str:
        weights = self.profile.typo_type_weights
        kinds = list(weights)
        return random.choices(kinds, weights=[weights[k] for k in kinds], k=1)[0]

    def _type_key(self, char: str, prev_char: str,
                  delay_scale: float = 1.0, dwell_scale: float = 1.0) -> str:
        """Sleep a human delay, then type one key with a sampled dwell time."""
        delay = self._get_inter_key_delay(prev_char, char) * delay_scale
        time.sleep(delay)
        self._type_char(char, self._sample_dwell(char) * dwell_scale)
        self.chars_typed += 1
        return char

    def _emit_typo(self, char: str, next_char: str, prev_char: str) -> int:
        """
        Perform one realistic mistake and its correction.
        Returns the number of source characters consumed (1 or 2), or 0.
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
            if not next_char.isalpha():
                return 0
            # Skip this character, type the next one, then notice and repair.
            self._type_key(next_char, prev_char, delay_scale=0.9)
            notice()
            fix()
            self._type_key(char, prev_char, delay_scale=0.8)
            self._type_key(next_char, char, delay_scale=0.9)
            return 2

        if kind == 'transposition':
            if not next_char.isalpha():
                return 0
            # Type the pair in the wrong order, then delete and retype it.
            self._type_key(next_char, prev_char, delay_scale=0.9)
            self._type_key(char, next_char, delay_scale=0.8)
            notice()
            fix()
            fix()
            self._type_key(char, prev_char, delay_scale=0.8)
            self._type_key(next_char, char, delay_scale=0.9)
            return 2

        return 0

    def _mouse_jitter(self):
        """Perform a random human-like mouse action via OS-level API."""
        try:
            self.mouse_sim.do_random_human_action()
        except Exception:
            pass  # Graceful fallback if mouse control fails

    def _type_char(self, char: str, dwell: float = None):
        """Type a single character using OS-level SendInput with hardware scan codes."""
        if char == '\n':
            _os_press_special('enter', dwell)
        elif char == '\t':
            _os_press_special('tab', dwell)
        else:
            _os_type_char_with_dwell(char, dwell)

    def _backspace(self):
        """Press backspace via OS-level SendInput."""
        _os_press_special('backspace')

    def _get_burst_tokens(self, file_ext: str) -> list:
        """Get burst tokens based on file type."""
        p = self.profile
        if file_ext in ('.cs', '.csproj'):
            return p.burst_tokens_csharp + p.burst_tokens_general
        return p.burst_tokens_general

    def _check_burst_token(self, text: str, position: int, tokens: list) -> str:
        remaining = text[position:]
        for token in sorted(tokens, key=len, reverse=True):
            if remaining.startswith(token):
                return token
        return None

    def _is_block_boundary(self, text: str, position: int) -> bool:
        """Check if we're at a logical block boundary (empty line after a block)."""
        if position < 2:
            return False
        # Two consecutive newlines = empty line = likely block boundary
        return text[position-1:position+1] == '\n\n'

    def _is_line_start(self, text: str, position: int) -> bool:
        """True when only indentation separates this position from a newline."""
        j = position
        while j > 0 and text[j-1] in ' \t':
            j -= 1
        return j == 0 or text[j-1] == '\n'

    def _starts_comment(self, text: str, position: int) -> bool:
        """Detect the start of a comment line so the typer can pause to read it."""
        if not self._is_line_start(text, position):
            return False
        return text.startswith(('//', '/*', '<!--', '#'), position)

    def save_file(self):
        """Press Ctrl+S to save the current file (OS-level)."""
        _os_hotkey('lctrl', 's')

    def close_file(self):
        """Press Ctrl+W to close the current tab (OS-level)."""
        time.sleep(random.uniform(0.25, 0.45))
        _os_hotkey('lctrl', 'w')

    def type_text(self, text: str, file_ext: str = '.txt') -> bool:
        """
        Type the given text with human-like behavior.
        Returns True if completed, False if stopped.
        """
        p = self.profile
        prev_char = ''
        i = 0
        burst_tokens = self._get_burst_tokens(file_ext)

        # Reading the first lines of a new file
        time.sleep(random.uniform(*p.pause_after_file_start))

        next_periodic_check = 0
        self._next_focus_check = 0
        while i < len(text):
            if self._stop_event.is_set():
                return False

            # ── Focus guard: cheap GetForegroundWindow() call every ~20 chars.
            #    Aborts the file if the target window is no longer focused. ──
            if self._focus_check is not None and i >= self._next_focus_check:
                self._next_focus_check = i + self._focus_check_interval
                if not self._focus_check():
                    return False

            char = text[i]

            # ── Poll the rest-break callback so long files still get the
            #    random 5-10 minute idle every 30-60 minutes. Checked at
            #    whitespace boundaries (and at least every 200 chars) so a
            #    break does not interrupt a word/token mid-way. ──
            if self._periodic_callback is not None and (
                    i >= next_periodic_check or char in ' \n\t'):
                next_periodic_check = i + 200
                self._periodic_callback()
                if self._stop_event.is_set():
                    return False

            # ── Rare long distraction (phone, conversation, ...) ──
            if random.random() < p.distraction_probability:
                time.sleep(random.uniform(*p.distraction_duration))

            # ── Block boundary pause (between functions/classes) ──
            if self._is_block_boundary(text, i):
                time.sleep(random.uniform(*p.pause_between_blocks))

            # ── Pause to read a comment line ──
            if (self._starts_comment(text, i)
                    and random.random() < p.pause_before_comment_prob):
                time.sleep(random.uniform(*p.pause_before_comment))

            # ── Check for burst token ──
            burst = self._check_burst_token(text, i, burst_tokens)
            if burst and random.random() < 0.7:
                for bc in burst:
                    if self._stop_event.is_set():
                        return False
                    # Bursts vary with small per-key noise (rhythm drift is
                    # already applied inside _get_inter_key_delay)
                    burst_mult = p.burst_speed_multiplier * random.uniform(0.85, 1.15)
                    delay = self._get_inter_key_delay(prev_char, bc) * burst_mult
                    time.sleep(delay)
                    self._type_char(bc, self._sample_dwell(bc) * 0.85)
                    prev_char = bc
                    self.chars_typed += 1
                i += len(burst)
                # Word-level pause after finishing a burst token (longer when tired)
                fatigue = self._fatigue_factor()
                time.sleep(random.uniform(*p.pause_after_word) *
                           (1.0 + fatigue * p.fatigue_pause_multiplier * 0.4))
                continue

            # ── Thinking pause (more frequent when tired) ──
            fatigue = self._fatigue_factor()
            pause_prob = p.pause_thinking_probability * (
                1.0 + fatigue * p.fatigue_pause_multiplier
            )
            if random.random() < pause_prob:
                time.sleep(random.uniform(*p.pause_thinking_duration))

            # ── OS-level mouse movement ──
            if random.random() < p.mouse_action_probability:
                self._mouse_jitter()

            # ── Typo injection (multiple realistic error types) ──
            consumed = 0
            if (char.isalpha() and i > 10
                    and random.random() < self._typo_probability_now()):
                next_char = text[i + 1] if i + 1 < len(text) else ''
                consumed = self._emit_typo(char, next_char, prev_char)

            if consumed:
                prev_char = text[i + consumed - 1]
                i += consumed
                # Brief settling pause after a correction
                time.sleep(random.uniform(0.03, 0.10))
                continue

            # ── Normal keystroke ──
            self._type_key(char, prev_char)

            # ── Post-character pauses (with natural randomness) ──
            if char == '\n':
                pause = random.uniform(*p.pause_after_newline)
                pause *= 1.0 + fatigue * p.fatigue_pause_multiplier * 0.5
                time.sleep(pause)
                # Small hesitation before starting a new (non-empty) line
                if i + 1 < len(text) and text[i + 1] != '\n':
                    time.sleep(random.uniform(*p.pause_after_line_start))
            elif char in '.;:':
                time.sleep(random.uniform(*p.pause_after_period))
            elif char in '{}':
                time.sleep(random.uniform(*p.pause_after_brace))
            elif char == ' ':
                # Word boundary pause - every word type has random inter-word delay
                if random.random() < p.pause_word_thinking_prob:
                    time.sleep(random.uniform(*p.pause_word_thinking))
                else:
                    time.sleep(random.uniform(*p.pause_after_word))
            elif prev_char.isalnum() and not char.isalnum() and char not in ' \t\r\n':
                # Transitioning from a word into punctuation/operators (e.g. "func(", "sum+")
                if random.random() < 0.35:
                    time.sleep(random.uniform(0.04, 0.12) / p.speed_multiplier)

            prev_char = char
            i += 1

        return True


# ──────────────────────────────────────────────
#  Project Scanner
# ──────────────────────────────────────────────

class ProjectScanner:
    """Scans a source directory and builds a list of files to type."""

    DEFAULT_EXTENSIONS = {
        '.cs', '.json', '.csproj', '.sln', '.html', '.css', '.js',
        '.md', '.txt', '.yml', '.yaml', '.config', '.razor', '.cshtml',
        '.py', '.ts', '.tsx', '.jsx', '.xml', '.env', '.gitignore',
        '.dockerignore', '.gitattributes', '.editorconfig', '.props',
        '.targets',
    }

    DEFAULT_SKIP_DIRS = {
        'bin', 'obj', '.git', '.vs', 'node_modules', '.idea',
        '__pycache__', '.vscode', 'packages', 'TestResults',
    }

    def __init__(self, source_dir: str, extensions: set = None, skip_dirs: set = None):
        self.source_dir = os.path.abspath(source_dir)
        self.extensions = extensions or self.DEFAULT_EXTENSIONS
        self.skip_dirs = skip_dirs or self.DEFAULT_SKIP_DIRS

    def scan(self) -> list:
        """
        Walk the source directory and return a list of files to type.
        Each entry is a dict with:
          - relative_path: path relative to source root
          - absolute_path: full path to the source file
          - size_bytes: file size
          - extension: file extension
        """
        files = []

        for root, dirs, filenames in os.walk(self.source_dir):
            # Filter out skipped directories (modifying dirs in-place)
            dirs[:] = [d for d in dirs if d not in self.skip_dirs]
            dirs.sort()

            for fname in sorted(filenames):
                ext = os.path.splitext(fname)[1].lower()
                # Dotfiles such as ".env" or ".gitignore" have no extension
                # according to splitext(), so match against the full name.
                if not ext:
                    ext = fname.lower()
                if ext not in self.extensions:
                    continue

                abs_path = os.path.join(root, fname)
                rel_path = os.path.relpath(abs_path, self.source_dir)

                try:
                    size = os.path.getsize(abs_path)
                except OSError:
                    continue

                # Skip very large files (> 100KB) — likely generated
                if size > 100 * 1024:
                    print(f"  [SKIP] {rel_path} ({size/1024:.0f}KB — too large)")
                    continue

                files.append({
                    'relative_path': rel_path,
                    'absolute_path': abs_path,
                    'size_bytes': size,
                    'extension': ext,
                })

        return files

    def estimate_typing_time(self, files: list, speed_multiplier: float = 1.0) -> float:
        """Estimate total typing time in minutes."""
        # Count actual characters (not bytes) so multi-byte files are not
        # overestimated. Fall back to the byte size if a file cannot be read.
        total_chars = 0
        for f in files:
            try:
                with open(f['absolute_path'], 'r', encoding='utf-8-sig',
                          errors='ignore') as fh:
                    total_chars += len(fh.read())
            except OSError:
                total_chars += f['size_bytes']
        # Rough estimate: ~3-5 chars/sec for human typing, plus pauses
        avg_chars_per_sec = 4.0 * speed_multiplier
        total_seconds = total_chars / avg_chars_per_sec
        # Add file-switching overhead (~5 sec per file)
        total_seconds += len(files) * 5
        return total_seconds / 60.0


# ──────────────────────────────────────────────
#  Project Typer — Orchestrator
# ──────────────────────────────────────────────

class ProjectTyper:
    """Orchestrates typing an entire project folder into VS Code."""

    def __init__(self, source_dir: str, target_dir: str,
                 speed: float = 1.0, open_delay: float = 2.0,
                 confirm_each: bool = False,
                 break_interval: tuple = (45.0, 60.0),
                 break_duration: tuple = (3.0, 4.0),
                 enable_breaks: bool = True,
                 target_window: str = None,
                 target_window_exact: bool = False,
                 focus_guard_enabled: bool = True,
                 stop_minutes: float = None):
        self.source_dir = os.path.abspath(source_dir)
        self.target_dir = os.path.abspath(target_dir)
        self.speed = speed
        self.open_delay = open_delay
        self.confirm_each = confirm_each
        self.break_interval = break_interval
        self.break_duration = break_duration
        self.enable_breaks = enable_breaks
        self.stop_minutes = stop_minutes
        self.stop_seconds = float(stop_minutes) * 60.0 if stop_minutes else None
        self.profile = TypingProfile(speed_multiplier=speed)
        self.typer = HumanTyper(self.profile)
        # Polled by HumanTyper while typing so time limit and rest breaks trigger gracefully
        self.typer._periodic_callback = self._periodic_check
        # Optional window pinning: type only into this window, never into
        # whatever happens to have focus.
        self.guard = None
        if target_window:
            self.guard = WindowGuard(
                target_window,
                exact=target_window_exact,
                refocus=focus_guard_enabled,
            )
            if focus_guard_enabled:
                self.typer._focus_check = self.guard.check
        self._progress_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'project_typer_progress.json'
        )
        self.session_start = time.time()
        self.next_break_after = random.uniform(
            self.break_interval[0] * 60, self.break_interval[1] * 60
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

    def _take_break_if_needed(self) -> bool:
        """
        Check if we have been typing for 30-60 minutes, and if so,
        take a random 3-4 minute break with a live countdown timer.
        Returns True if a break was taken.
        """
        if not self.enable_breaks:
            return False

        elapsed = time.time() - self.session_start
        if elapsed < self.next_break_after:
            return False

        # Random break duration between 3 and 4 minutes (in seconds)
        break_duration_sec = random.uniform(
            self.break_duration[0] * 60, self.break_duration[1] * 60
        )
        break_mins = break_duration_sec / 60.0
        work_mins = elapsed / 60.0
        resume_dt = datetime.fromtimestamp(time.time() + break_duration_sec).strftime('%H:%M:%S')

        print(f"\n{'☕ '*25}")
        print(f"  HUMAN REST BREAK")
        print(f"  Session typing time: {work_mins:.1f} minutes")
        print(f"  Taking a break for:  {break_mins:.1f} minutes ({int(break_duration_sec)} seconds)")
        print(f"  Resuming at:         {resume_dt}")
        print(f"{'☕ '*25}\n")

        start_break = time.time()
        while (time.time() - start_break) < break_duration_sec:
            if self.typer._stop_event.is_set():
                self.session_start = time.time()
                return True
            remaining = int(break_duration_sec - (time.time() - start_break))
            mins_rem = remaining // 60
            secs_rem = remaining % 60
            print(f"  Sleeping... {mins_rem:02d}:{secs_rem:02d} remaining (Press Ctrl+C to abort)", end='\r')
            time.sleep(1)

        print(f"\n  ✓ Break finished! Continuing typing...\n")

        # Schedule the next random 30-60 minute typing session
        self.session_start = time.time()
        self.next_break_after = random.uniform(
            self.break_interval[0] * 60, self.break_interval[1] * 60
        )
        print(f"  Next break scheduled in ~{self.next_break_after / 60.0:.1f} minutes.\n")
        return True

    def _create_target_structure(self, files: list):
        """Pre-create all necessary subdirectories in the target folder."""
        dirs_created = set()
        for f in files:
            target_path = os.path.join(self.target_dir, f['relative_path'])
            target_dir = os.path.dirname(target_path)
            if target_dir not in dirs_created:
                os.makedirs(target_dir, exist_ok=True)
                dirs_created.add(target_dir)
        print(f"  Created {len(dirs_created)} directories in target folder.")

    def _write_vscode_settings(self):
        """
        Write workspace settings that stop VS Code from interfering with
        simulated typing (auto-indent, auto-close, suggestions, Emmet, ...).

        Without this, pressing Enter makes VS Code add indentation on top of
        the file's own indentation, and Enter/Tab may accept autocomplete items
        instead of inserting a newline/indent — corrupting the typed file.
        """
        vscode_dir = os.path.join(self.target_dir, '.vscode')
        os.makedirs(vscode_dir, exist_ok=True)
        settings_path = os.path.join(vscode_dir, 'settings.json')

        required = {
            'editor.autoIndent': 'none',
            'editor.detectIndentation': False,
            'editor.insertSpaces': False,
            'editor.autoClosingBrackets': 'never',
            'editor.autoClosingQuotes': 'never',
            'editor.autoSurround': 'never',
            'editor.linkedEditing': False,
            'editor.acceptSuggestionOnEnter': 'off',
            'editor.quickSuggestions': False,
            'editor.suggestOnTriggerCharacters': False,
            'editor.tabCompletion': 'off',
            'editor.snippetSuggestions': 'none',
            'editor.wordBasedSuggestions': 'off',
            'editor.formatOnType': False,
            'editor.parameterHints.enabled': False,
            'editor.hover.enabled': False,
            'editor.trimAutoWhitespace': False,
            'files.trimTrailingWhitespace': False,
            'files.insertFinalNewline': False,
            'files.trimFinalNewlines': False,
            'emmet.triggerExpansionOnTab': False,
            'html.autoClosingTags': False,
            'javascript.autoClosingTags': False,
            'typescript.autoClosingTags': False,
        }

        existing = {}
        if os.path.exists(settings_path):
            try:
                with open(settings_path, 'r', encoding='utf-8-sig') as f:
                    existing = json.load(f)
                if not isinstance(existing, dict):
                    existing = {}
            except (OSError, ValueError):
                # Preserve an unreadable settings file instead of losing it.
                backup = settings_path + '.bak'
                try:
                    os.replace(settings_path, backup)
                    print(f"  [WARN] Invalid settings.json backed up to {backup}")
                except OSError:
                    pass
                existing = {}

        existing.update(required)
        with open(settings_path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=4)
            f.write('\n')
        print(f"  Wrote VS Code settings: {settings_path}")

    def _open_file_in_vscode(self, filepath: str):
        """Open a file in VS Code using the CLI (non-blocking)."""
        # Create the file first (empty) so VS Code opens it
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        if not os.path.exists(filepath):
            with open(filepath, 'w', encoding='utf-8'):
                pass  # Create empty file

        creation_flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
        subprocess.Popen(
            f'code "{filepath}"',
            shell=True,
            creationflags=creation_flags,
        )
        time.sleep(random.uniform(self.open_delay * 0.85, self.open_delay * 1.25))

    def _clear_active_editor(self):
        """
        Select-all + delete in the focused editor so a partially typed file from
        an interrupted run is not duplicated when typing starts again.
        """
        _os_hotkey('lctrl', 'a')
        time.sleep(random.uniform(0.05, 0.12))
        _os_press_special('delete')
        time.sleep(random.uniform(0.15, 0.35))

    def _save_progress(self, file_index: int, total: int, current_file: str):
        """Save progress so we can resume if interrupted."""
        progress = {
            'source_dir': self.source_dir,
            'target_dir': self.target_dir,
            'last_completed_index': file_index,
            'total_files': total,
            'current_file': current_file,
            'timestamp': datetime.now().isoformat(),
        }
        with open(self._progress_file, 'w') as f:
            json.dump(progress, f, indent=2)

    def run(self, files: list, resume_from: int = 0):
        """
        Main execution loop — types each file into VS Code.

        Args:
            files: List of file dicts from ProjectScanner.scan()
            resume_from: Index to resume from (0-based)
        """
        total = len(files)

        print(f"\n{'═'*60}")
        print(f"  PROJECT TYPER")
        print(f"  Source: {self.source_dir}")
        print(f"  Target: {self.target_dir}")
        print(f"  Files:  {total} (starting from #{resume_from})")
        print(f"  Speed:  {self.speed}x")
        if self.stop_minutes:
            stop_dt = datetime.fromtimestamp(self.session_start + self.stop_seconds).strftime('%H:%M:%S')
            print(f"  Stop limit: {self.stop_minutes:.1f} minutes (will stop at {stop_dt})")
        else:
            print(f"  Stop limit: None (runs continuously)")
        if self.enable_breaks:
            print(f"  Breaks: Random {self.break_duration[0]:.0f}-{self.break_duration[1]:.0f}m rest every {self.break_interval[0]:.0f}-{self.break_interval[1]:.0f}m")
            print(f"  First break in: ~{self.next_break_after / 60.0:.1f} minutes")
        print(f"{'═'*60}")

        # Resolve the target window before anything is typed. Failing here is
        # much better than discovering it after 300 lines went to Notepad.
        if self.guard is not None:
            if not self.guard.resolve():
                print("\n  Aborting — no usable target window.")
                raise SystemExit(1)
            if not self.guard.ensure_focus():
                print("\n  Aborting — could not focus the target window.")
                raise SystemExit(1)

        # Create folder structure and disable VS Code's auto-editing features
        self._create_target_structure(files)
        self._write_vscode_settings()

        # Countdown before starting
        if self.guard is not None:
            print(f"\n  ⚠ Typing is locked to: {_safe_text(self.guard.title)}")
            print(f"  ⚠ Do NOT switch windows while typing is in progress!")
        else:
            print(f"\n  ⚠ Make sure VS Code is open with the target folder!")
            print(f"  ⚠ Do NOT touch keyboard/mouse while typing is in progress!")
        print(f"\n  Starting in 8 seconds... (Ctrl+C to abort)\n")
        for i in range(8, 0, -1):
            print(f"  {i}...", end='\r')
            time.sleep(1)
        print(f"  {'Starting now!':<30}")

        for idx in range(resume_from, total):
            if self.typer._stop_event.is_set() or self._is_time_up():
                if self._is_time_up():
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*60}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at file #{idx + 1}")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*60}\n")
                    self._save_progress(idx - 1, total, files[idx]['relative_path'] if idx < total else '')
                else:
                    print(f"\n[Stopped] Progress saved at file #{idx}")
                break

            file_info = files[idx]
            rel_path = file_info['relative_path']
            abs_source = file_info['absolute_path']
            target_path = os.path.join(self.target_dir, rel_path)
            ext = file_info['extension']

            print(f"\n{'─'*60}")
            print(f"  [{idx+1}/{total}] {rel_path}")
            print(f"  Size: {file_info['size_bytes']} bytes")

            # Confirm if needed
            if self.confirm_each:
                resp = input("  Type this file? [Y/n/skip/quit]: ").strip().lower()
                if resp == 'n' or resp == 'skip':
                    print("  [Skipped]")
                    continue
                elif resp == 'quit' or resp == 'q':
                    print("  [Quit by user]")
                    break

            # Read source file content (utf-8-sig strips a leading BOM so it
            # is not typed into the target as a stray U+FEFF character)
            try:
                with open(abs_source, 'r', encoding='utf-8-sig', errors='replace') as f:
                    content = f.read()
            except Exception as e:
                print(f"  [ERROR] Cannot read source file: {e}")
                continue

            if not content.strip():
                # Empty file — just create it
                with open(target_path, 'w', encoding='utf-8') as f:
                    pass
                print("  [Empty file — created]")
                continue

            # Open the file in VS Code
            print(f"  Opening in VS Code...")
            had_existing_content = (
                os.path.exists(target_path) and os.path.getsize(target_path) > 0
            )
            self._open_file_in_vscode(target_path)

            # Small extra wait for VS Code to fully load
            time.sleep(random.uniform(0.5, 1.5))

            # Re-assert focus: the `code` CLI can open the file in a different
            # window than the one we locked onto.
            if self.guard is not None and not self.guard.ensure_focus():
                print("  [FOCUS] Aborting run to avoid typing into the wrong "
                      "window.")
                self._save_progress(idx - 1, total, rel_path)
                break

            # Clear stale/partial content so a resumed run cannot duplicate it
            if had_existing_content:
                print("  Clearing existing content...")
                self._clear_active_editor()

            # Reset fatigue between files
            self.typer.reset_fatigue()

            # Type the file contents
            print(f"  Typing {len(content)} characters...")
            start_time = time.time()
            completed = self.typer.type_text(content, file_ext=ext)
            elapsed = time.time() - start_time

            if completed:
                # Save the file
                time.sleep(random.uniform(0.3, 0.8))
                self.typer.save_file()
                time.sleep(random.uniform(0.5, 1.0))

                chars_per_sec = len(content) / elapsed if elapsed > 0 else 0
                print(f"  ✓ Done ({elapsed:.1f}s, {chars_per_sec:.1f} chars/sec)")

                # Save progress
                self._save_progress(idx, total, rel_path)

                # Check if time limit was reached right as file completed
                if self._is_time_up():
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*60}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Completed file #{idx + 1}. Next run starts at #{idx + 2}.")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*60}\n")
                    break
            else:
                if self._is_time_up():
                    elapsed_m = (time.time() - self.session_start) / 60.0
                    print(f"\n\n{'═'*60}")
                    print(f"  TIME LIMIT REACHED (--stop {self.stop_minutes:.1f} min)")
                    print(f"  Session ran for {elapsed_m:.1f} minutes.")
                    print(f"  Progress cleanly saved at file #{idx + 1}: {rel_path}")
                    print(f"  Run the command again anytime to auto-resume!")
                    print(f"{'═'*60}\n")
                    self._save_progress(idx - 1, total, rel_path)
                elif self.typer._stop_event.is_set():
                    print(f"  ✗ Interrupted at file #{idx}")
                    self._save_progress(idx - 1, total, rel_path)
                else:
                    print(f"  ✗ Aborted at file #{idx} (target window lost focus)")
                    self._save_progress(idx - 1, total, rel_path)
                break

            # Pause between files (like switching mental context)
            if idx < total - 1:
                # Check if it's time for a 5-10 min break (after 30-60 mins of typing)
                if not self._take_break_if_needed():
                    pause = random.uniform(2.0, 5.0)
                    print(f"  Pausing {pause:.1f}s before next file...")
                    time.sleep(pause)

        print(f"\n{'═'*60}")
        print(f"  PROJECT TYPER — COMPLETE")
        print(f"  Total characters typed: {self.typer.chars_typed}")
        if self.guard is not None:
            print(f"  Target window: {self.guard.summary()}")
        print(f"{'═'*60}\n")


# ──────────────────────────────────────────────
#  CLI Entry Point
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Human-Like Project Typer — Types an entire project folder into VS Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run — see what files would be typed
  python project_typer.py --source "C:\\project" --target "C:\\output" --dry-run

  # Type at normal speed
  python project_typer.py --source "C:\\project" --target "C:\\output"

  # Type faster (2x speed)
  python project_typer.py --source "C:\\project" --target "C:\\output" --speed 2.0

  # Resume from file #10
  python project_typer.py --source "C:\\project" --target "C:\\output" --resume 10

  # Confirm each file before typing
  python project_typer.py --source "C:\\project" --target "C:\\output" --confirm

  # Lock typing to one window — abort instead of typing into the wrong app
  python project_typer.py --source "C:\\project" --target "C:\\output" --target-window "Visual Studio Code"
        """
    )

    parser.add_argument('--source', required=True,
                        help='Source folder to read files from')
    parser.add_argument('--target', required=True,
                        help='Target folder to type files into')
    parser.add_argument('--speed', type=float, default=1.0,
                        help='Typing speed multiplier (0.5=slow, 1.0=normal, 2.0=fast)')
    parser.add_argument('--wpm', type=float, default=None,
                        help='Target words-per-minute (approx., overrides --speed)')
    parser.add_argument('--calibrate', type=str, default=None,
                        help='Personalise timing from a typing_detector recording (JSON)')
    parser.add_argument('--extensions', type=str, default=None,
                        help='Comma-separated file extensions (e.g. ".cs,.json,.html")')
    parser.add_argument('--skip-dirs', type=str, default=None,
                        help='Comma-separated directory names to skip')
    parser.add_argument('--delay', type=float, default=2.0,
                        help='Seconds to wait after opening each file in VS Code')
    parser.add_argument('--dry-run', action='store_true',
                        help='List files without typing')
    parser.add_argument('--resume', type=int, default=None,
                        help='Resume from file index (0-based). '
                             'If omitted, saved progress is used automatically')
    parser.add_argument('--confirm', action='store_true',
                        help='Confirm before typing each file')
    parser.add_argument('--break-interval', type=str, default='45,60',
                        help='Work duration range in minutes before break [default: 45,60]')
    parser.add_argument('--break-duration', type=str, default='3,4',
                        help='Break sleep duration range in minutes [default: 3,4]')
    parser.add_argument('--no-breaks', action='store_true',
                        help='Disable automatic 45-60 min rest breaks')
    parser.add_argument('--stop', type=float, default=None,
                        metavar='MINUTES',
                        help='Stop the script after working for N minutes (e.g. --stop 30). '
                             'Saves progress cleanly and exits. (Default: run continuously)')
    parser.add_argument('--target-window', type=str, default=None,
                        metavar='TITLE',
                        help='Only type into the window whose title contains '
                             'TITLE (case-insensitive). Aborts instead of typing '
                             'into the wrong window. e.g. --target-window "Visual '
                             'Studio Code"')
    parser.add_argument('--target-window-exact', action='store_true',
                        help='Require an exact title match instead of a substring')
    parser.add_argument('--no-focus-guard', action='store_true',
                        help='With --target-window: resolve the window but do not '
                             're-focus it or abort when focus is lost')

    args = parser.parse_args()

    # Validate paths
    if not os.path.isdir(args.source):
        print(f"Error: Source folder not found: {args.source}")
        sys.exit(1)

    if (args.target_window_exact or args.no_focus_guard) and not args.target_window:
        print("Error: --target-window-exact and --no-focus-guard require "
              "--target-window")
        sys.exit(1)

    # Optional target speed in words per minute (~5 chars per word)
    if args.wpm is not None:
        if not 10 <= args.wpm <= 220:
            print("Error: --wpm must be between 10 and 220")
            sys.exit(1)
        args.speed = max(0.15, min(6.0, args.wpm / 60.0))
        print(f"Target speed: ~{args.wpm:.0f} WPM "
              f"(speed multiplier {args.speed:.2f})")

    # Parse extensions
    extensions = None
    if args.extensions:
        extensions = set(e.strip() if e.startswith('.') else f'.{e.strip()}'
                         for e in args.extensions.split(','))

    # Parse skip dirs
    skip_dirs = None
    if args.skip_dirs:
        skip_dirs = set(d.strip() for d in args.skip_dirs.split(','))

    # Scan source folder
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Project Typer — Human-Like Folder Replication   ║")
    print("║     Educational / Research Use Only                  ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()
    print(f"Scanning source folder: {args.source}")

    scanner = ProjectScanner(args.source, extensions=extensions, skip_dirs=skip_dirs)
    files = scanner.scan()

    if not files:
        print("No matching files found in source folder!")
        sys.exit(1)

    # Sort files — .sln and .csproj first, then alphabetically
    priority_exts = ['.sln', '.csproj', '.json', '.xml', '.config']
    def sort_key(f):
        ext = f['extension']
        priority = priority_exts.index(ext) if ext in priority_exts else len(priority_exts)
        return (priority, f['relative_path'])
    files.sort(key=sort_key)

    # Determine where to resume from (explicit --resume or saved progress)
    resume_from = args.resume
    if resume_from is None:
        resume_from = 0
        progress_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'project_typer_progress.json'
        )
        if os.path.exists(progress_path):
            try:
                with open(progress_path, 'r', encoding='utf-8') as f:
                    progress = json.load(f)
                same_source = os.path.abspath(progress.get('source_dir', '')) == os.path.abspath(args.source)
                same_target = os.path.abspath(progress.get('target_dir', '')) == os.path.abspath(args.target)
                same_count = progress.get('total_files') == len(files)
                saved_next = int(progress.get('last_completed_index', -1)) + 1
                if same_source and same_target and same_count and 0 < saved_next < len(files):
                    resume_from = saved_next
                    print(f"\nFound saved progress: resuming from file #{resume_from}.")
                    print("Pass --resume 0 to start over from the beginning.")
            except (OSError, ValueError, TypeError):
                resume_from = 0
    if resume_from < 0 or resume_from >= len(files):
        resume_from = 0

    # Print file list
    total_size = sum(f['size_bytes'] for f in files)
    est_time = scanner.estimate_typing_time(files, args.speed)

    print(f"\nFound {len(files)} files ({total_size/1024:.1f} KB total)")
    print(f"Estimated typing time: {est_time:.0f} minutes ({est_time/60:.1f} hours)")
    print()

    print("Files to type:")
    print("─" * 70)
    for i, f in enumerate(files):
        marker = " →" if i >= resume_from else "  "
        size_str = f"{f['size_bytes']:>6}"
        print(f"  {marker} [{i:3d}] {f['relative_path']:<50} {size_str}B")
    print("─" * 70)

    # Validate --target-window up front, including for a dry run, so a typo in
    # the title is caught before any typing starts.
    if args.target_window:
        matches = find_windows(args.target_window,
                               exact=args.target_window_exact)
        print()
        if not matches:
            print(f"Target window: NO MATCH for {args.target_window!r}")
            print("Visible windows right now:")
            for w in _list_windows()[:15]:
                print(f"  - {_safe_text(w['title'])}")
        else:
            print(f"Target window match ({len(matches)}):")
            for w in matches:
                print(f"  - {_safe_text(w['title'])}  (pid {w['pid']})")

    if args.dry_run:
        print("\n[Dry run complete — no files were typed]")
        sys.exit(0)

    # Confirm
    print(f"\nTarget folder: {args.target}")
    resp = input("\nProceed with typing? [y/N]: ").strip().lower()
    if resp != 'y':
        print("Aborted.")
        sys.exit(0)

    # Parse breaks
    try:
        b_int = tuple(float(x.strip()) for x in args.break_interval.split(','))
        if len(b_int) != 2:
            b_int = (45.0, 60.0)
    except Exception:
        b_int = (45.0, 60.0)

    try:
        b_dur = tuple(float(x.strip()) for x in args.break_duration.split(','))
        if len(b_dur) != 2:
            b_dur = (3.0, 4.0)
    except Exception:
        b_dur = (3.0, 4.0)

    # Run the project typer
    project_typer = ProjectTyper(
        source_dir=args.source,
        target_dir=args.target,
        speed=args.speed,
        open_delay=args.delay,
        confirm_each=args.confirm,
        break_interval=b_int,
        break_duration=b_dur,
        enable_breaks=not args.no_breaks,
        target_window=args.target_window,
        target_window_exact=args.target_window_exact,
        focus_guard_enabled=not args.no_focus_guard,
        stop_minutes=args.stop,
    )

    # Optional: personalise the profile from a real keystroke recording
    if args.calibrate:
        if not os.path.exists(args.calibrate):
            print(f"Error: calibration recording not found: {args.calibrate}")
            sys.exit(1)
        try:
            with open(args.calibrate, 'r', encoding='utf-8') as f:
                recording = json.load(f)
            summary = calibrate_profile_from_recording(
                project_typer.profile, recording
            )
            print("\nCalibrated from recording:")
            print(f"  samples:        {summary['samples']}")
            print(f"  mean IKI:       {summary['mean_iki_ms']:.0f} ms")
            print(f"  p10/p50/p90:    {summary['p10_ms']:.0f} / "
                  f"{summary['p50_ms']:.0f} / {summary['p90_ms']:.0f} ms")
            if summary['dwell_mean_ms'] is not None:
                print(f"  mean dwell:     {summary['dwell_mean_ms']:.0f} ms "
                      f"({summary['dwell_samples']} samples)")
            print(f"  backspace rate: {summary['backspace_ratio']*100:.1f}% "
                  f"-> typo probability {summary['typo_probability']*100:.1f}%")
        except (OSError, ValueError, KeyError) as exc:
            print(f"[WARN] Calibration failed: {exc}")

    try:
        project_typer.run(files, resume_from=resume_from)
    except KeyboardInterrupt:
        project_typer.typer.stop()
        print("\n\n[Aborted by user — progress saved]")


if __name__ == "__main__":
    main()
