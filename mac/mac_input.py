"""
macOS platform layer for project_typer.py / excel_typer.py
==========================================================
This module is the macOS equivalent of the Windows ``user32.dll`` SendInput
layer used by the original scripts.

Everything here posts *real* OS-level events through Quartz Event Services
(CoreGraphics), which is the same path a physical keyboard/mouse takes:

    Python -> Quartz CGEventCreateKeyboardEvent / CGEventPost -> WindowServer
           -> Application

Requirements
------------
1. Install the pyobjc frameworks::

       pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa

2. Grant the terminal app (Terminal / iTerm2 / VS Code) Accessibility
   permission::

       System Settings -> Privacy & Security -> Accessibility

   Without that permission macOS silently drops every synthetic event.

Notes
-----
* Window *titles* (``kCGWindowName``) require Screen Recording permission on
  macOS 10.15+. The window *owner* name (e.g. "Visual Studio Code",
  "Microsoft Excel") is always available, so ``--target-window`` still works
  by app name even without Screen Recording.
* This module deliberately exposes the same helper names the original Windows
  scripts used (``_os_type_char_with_dwell``, ``_send_mouse_input``,
  ``find_windows``, ``WindowGuard``, ...) so the rest of the code is unchanged.
"""

import os
import sys
import time
import math
import random
import subprocess

try:
    import Quartz
    import AppKit
except ImportError as _exc:  # pragma: no cover - only hit on missing deps
    raise SystemExit(
        "\n[macOS] Missing pyobjc frameworks.\n"
        "Install them with:\n"
        "    pip install pyobjc-framework-Quartz pyobjc-framework-Cocoa\n"
        f"(import error: {_exc})\n"
    )

# ──────────────────────────────────────────────
#  Mouse event constants (kept identical to the Windows names so the
#  existing HumanMouseSimulator code can stay untouched)
# ──────────────────────────────────────────────
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004

# ──────────────────────────────────────────────
#  macOS virtual key codes (kVK_*)
#  The dict keys match the Windows VK_TO_SCAN keys so the typer code that
#  says 'enter', 'tab', 'backspace', 'lctrl', ... keeps working unchanged.
# ──────────────────────────────────────────────
MAC_KEYCODE = {
    # Letters
    'a': 0x00, 's': 0x01, 'd': 0x02, 'f': 0x03, 'h': 0x04,
    'g': 0x05, 'z': 0x06, 'x': 0x07, 'c': 0x08, 'v': 0x09,
    'b': 0x0B, 'q': 0x0C, 'w': 0x0D, 'e': 0x0E, 'r': 0x0F,
    'y': 0x10, 't': 0x11, 'o': 0x1F, 'u': 0x20, 'i': 0x22,
    'p': 0x23, 'l': 0x25, 'j': 0x26, 'k': 0x28, 'n': 0x2D,
    'm': 0x2E,
    # Number row
    '1': 0x12, '2': 0x13, '3': 0x14, '4': 0x15, '6': 0x16,
    '5': 0x17, '9': 0x19, '7': 0x1A, '8': 0x1C, '0': 0x1D,
    # Symbols (unshifted)
    '-': 0x1B, '=': 0x18, '[': 0x21, ']': 0x1E, '\\': 0x2A,
    ';': 0x29, "'": 0x27, '`': 0x32, ',': 0x2B, '.': 0x2F,
    '/': 0x2C, ' ': 0x31,
    # Navigation / control keys
    'enter': 0x24, 'tab': 0x30, 'backspace': 0x33,
    'lshift': 0x38, 'rshift': 0x3C,
    'lctrl': 0x3B, 'rctrl': 0x3E,
    'lalt': 0x3A, 'ralt': 0x3D,          # Option
    'lcmd': 0x37, 'rcmd': 0x36,          # Command
    'capslock': 0x39, 'escape': 0x35,
    'delete': 0x75,                      # forward delete
    'home': 0x73, 'end': 0x77,
    'pageup': 0x74, 'pagedown': 0x79,
    'up': 0x7E, 'down': 0x7D, 'left': 0x7B, 'right': 0x7C,
    'f1': 0x7A, 'f2': 0x78, 'f3': 0x63, 'f4': 0x76,
    'f5': 0x60, 'f6': 0x61, 'f7': 0x62, 'f8': 0x64,
    'f9': 0x65, 'f10': 0x6D, 'f11': 0x67, 'f12': 0x6F,
}

# Characters that require Shift on a US Mac keyboard
SHIFT_MAP = {
    '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']', '|': '\\',
    ':': ';', '"': "'", '~': '`', '<': ',', '>': '.',
    '?': '/',
}

# Modifier key name -> Quartz event flag
MOD_FLAGS = {
    'lshift': Quartz.kCGEventFlagMaskShift,
    'rshift': Quartz.kCGEventFlagMaskShift,
    'lctrl': Quartz.kCGEventFlagMaskControl,
    'rctrl': Quartz.kCGEventFlagMaskControl,
    'lalt': Quartz.kCGEventFlagMaskAlternate,
    'ralt': Quartz.kCGEventFlagMaskAlternate,
    'lcmd': Quartz.kCGEventFlagMaskCommand,
    'rcmd': Quartz.kCGEventFlagMaskCommand,
}

_EVENT_SOURCE = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)


# ──────────────────────────────────────────────
#  Permission helpers
# ──────────────────────────────────────────────

def accessibility_trusted() -> bool:
    """True when this process may post synthetic events (Accessibility)."""
    try:
        return bool(Quartz.CGPreflightPostEventAccess())
    except Exception:
        return True  # API unavailable on this macOS version — assume OK


def request_accessibility() -> None:
    """Trigger the macOS Accessibility permission prompt (best effort)."""
    try:
        Quartz.CGRequestPostEventAccess()
    except Exception:
        pass


def check_accessibility(verbose: bool = True) -> bool:
    """
    Warn once if the terminal has not been granted Accessibility permission.
    Synthetic keystrokes are silently discarded otherwise.
    """
    if accessibility_trusted():
        return True
    if verbose:
        print("\n  [macOS] ⚠ Accessibility permission is NOT granted.")
        print("          System Settings → Privacy & Security → Accessibility")
        print("          Add and enable your terminal app (Terminal / iTerm / VS Code).")
        print("          macOS will drop every simulated keystroke until you do.\n")
    request_accessibility()
    return False


# ──────────────────────────────────────────────
#  Low-level event posting
# ──────────────────────────────────────────────

def _post(event) -> None:
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


def _key_event(keycode: int, down: bool, flags: int = 0) -> None:
    event = Quartz.CGEventCreateKeyboardEvent(_EVENT_SOURCE, keycode, bool(down))
    if event is None:
        return
    if flags:
        Quartz.CGEventSetFlags(event, flags)
    _post(event)


def _os_key_press(scan_code: int) -> None:
    """Press a key by macOS virtual key code (OS-level)."""
    _key_event(int(scan_code), True)


def _os_key_release(scan_code: int) -> None:
    """Release a key by macOS virtual key code (OS-level)."""
    _key_event(int(scan_code), False)


def _os_type_unicode(char: str) -> None:
    """
    Type a Unicode character via CGEventKeyboardSetUnicodeString.
    Used as a fallback for characters that have no dedicated key code
    (accented letters, emoji, CJK, ...).
    """
    for c in char:
        units = len(c.encode('utf-16-le')) // 2
        down_event = Quartz.CGEventCreateKeyboardEvent(_EVENT_SOURCE, 0, True)
        if down_event is None:
            continue
        try:
            Quartz.CGEventKeyboardSetUnicodeString(down_event, units, c)
        except Exception:
            return
        _post(down_event)

        # Plain key-up (no string) so the character is not inserted twice.
        up_event = Quartz.CGEventCreateKeyboardEvent(_EVENT_SOURCE, 0, False)
        if up_event is not None:
            _post(up_event)


def _os_type_char_with_dwell(char: str, dwell_time: float = None) -> None:
    """
    Type a single character at the OS level with realistic key dwell time.
    Handles Shift for uppercase letters and shifted symbols automatically.
    """
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

    keycode = MAC_KEYCODE.get(base_char)
    if keycode is None:
        _os_type_unicode(char)
        return

    shift_flag = Quartz.kCGEventFlagMaskShift
    flags = shift_flag if needs_shift else 0

    if needs_shift:
        _key_event(MAC_KEYCODE['lshift'], True, shift_flag)
        time.sleep(random.uniform(0.015, 0.04))  # Shift lands before the key

    _key_event(keycode, True, flags)
    time.sleep(dwell_time)
    _key_event(keycode, False, flags)

    if needs_shift:
        time.sleep(random.uniform(0.01, 0.03))
        _key_event(MAC_KEYCODE['lshift'], False, 0)


def _os_press_special(key_name: str, dwell_time: float = None) -> None:
    """Press and release a special key (Enter, Tab, Backspace, ...)."""
    if dwell_time is None:
        dwell_time = random.uniform(0.05, 0.12)

    keycode = MAC_KEYCODE.get(key_name)
    if keycode is None:
        return

    _key_event(keycode, True)
    time.sleep(dwell_time)
    _key_event(keycode, False)


def _os_hotkey(modifier: str, key_char: str) -> None:
    """
    Press a single-modifier shortcut (e.g. Cmd+S) at the OS level with
    natural modifier-hold timing. On macOS the "primary" modifier is
    ``lcmd`` (Command), not ``lctrl``.
    """
    mod_code = MAC_KEYCODE.get(modifier)
    key_code = MAC_KEYCODE.get(key_char)
    if mod_code is None or key_code is None:
        return

    flag = MOD_FLAGS.get(modifier, 0)
    _key_event(mod_code, True, flag)
    time.sleep(random.uniform(0.03, 0.07))
    _key_event(key_code, True, flag)
    time.sleep(random.uniform(0.05, 0.10))
    _key_event(key_code, False, flag)
    time.sleep(random.uniform(0.02, 0.05))
    _key_event(mod_code, False, 0)


def _os_hotkey_multi(modifiers, key_char: str) -> None:
    """
    Press a multi-modifier shortcut (e.g. Ctrl+Option+Return for an in-cell
    line break in Excel for Mac). ``modifiers`` is an iterable of key names.
    """
    key_code = MAC_KEYCODE.get(key_char)
    mods = [m for m in modifiers if m in MAC_KEYCODE]
    if key_code is None or not mods:
        return

    flags = 0
    for m in mods:
        flags |= MOD_FLAGS.get(m, 0)

    for m in mods:
        _key_event(MAC_KEYCODE[m], True, flags)
        time.sleep(random.uniform(0.015, 0.04))
    _key_event(key_code, True, flags)
    time.sleep(random.uniform(0.05, 0.10))
    _key_event(key_code, False, flags)
    time.sleep(random.uniform(0.02, 0.05))
    for m in reversed(mods):
        _key_event(MAC_KEYCODE[m], False, 0)
        time.sleep(random.uniform(0.01, 0.03))


# ──────────────────────────────────────────────
#  Mouse (Quartz)
# ──────────────────────────────────────────────

def _get_cursor_pos():
    """Return the current mouse cursor position in screen pixels."""
    event = Quartz.CGEventCreate(None)
    point = Quartz.CGEventGetLocation(event)
    return int(point.x), int(point.y)


def _get_screen_size():
    """
    Return the main display size in *points* (the coordinate space used by
    CGEvent mouse positions and by the simulator's region maths).

    Do NOT use CGDisplayPixelsWide/High here: on a Retina display those are
    backing pixels (2x the points), which would place the cursor at half the
    intended position.
    """
    display = Quartz.CGMainDisplayID()
    try:
        bounds = Quartz.CGDisplayBounds(display)
        return int(bounds.size.width), int(bounds.size.height)
    except Exception:
        return (int(Quartz.CGDisplayPixelsWide(display)),
                int(Quartz.CGDisplayPixelsHigh(display)))


def _mouse_event(kind, x, y, button=Quartz.kCGMouseButtonLeft) -> None:
    event = Quartz.CGEventCreateMouseEvent(_EVENT_SOURCE, kind, (x, y), button)
    if event is not None:
        _post(event)


def _send_mouse_input(dx: int, dy: int, mouse_data: int = 0,
                      flags: int = MOUSEEVENTF_MOVE) -> None:
    """
    Compatibility shim for the Windows ``_send_mouse_input``.

    The existing simulators pass ABSOLUTE coordinates in the Windows
    0..65535 range, so they are converted back to pixels here. Wheel deltas
    are also converted from Windows WHEEL_DELTA (120 per notch) to macOS
    line units.
    """
    if flags & MOUSEEVENTF_ABSOLUTE:
        w, h = _get_screen_size()
        x = int(round(dx * (w - 1) / 65535.0))
        y = int(round(dy * (h - 1) / 65535.0))
        _mouse_event(Quartz.kCGEventMouseMoved, x, y)
    elif flags & MOUSEEVENTF_WHEEL:
        delta = int(mouse_data)
        if delta >= 0x80000000:  # signed 32-bit
            delta -= 0x100000000
        lines = int(round(delta / 120.0))
        if lines == 0:
            lines = 1 if delta > 0 else -1
        event = Quartz.CGEventCreateScrollWheelEvent(
            _EVENT_SOURCE, Quartz.kCGScrollEventUnitLine, 1, lines
        )
        if event is not None:
            _post(event)
    elif flags & MOUSEEVENTF_LEFTDOWN:
        x, y = _get_cursor_pos()
        _mouse_event(Quartz.kCGEventLeftMouseDown, x, y)
    elif flags & MOUSEEVENTF_LEFTUP:
        x, y = _get_cursor_pos()
        _mouse_event(Quartz.kCGEventLeftMouseUp, x, y)
    else:
        x, y = _get_cursor_pos()
        _mouse_event(Quartz.kCGEventMouseMoved, x + int(dx), y + int(dy))


# ──────────────────────────────────────────────
#  Window discovery / focus (Quartz + AppKit)
# ──────────────────────────────────────────────

def _safe_text(text: str) -> str:
    """Make an arbitrary window title safe to print."""
    encoding = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        text.encode(encoding)
        return text
    except (UnicodeEncodeError, LookupError):
        return text.encode(encoding, errors='replace').decode(
            encoding, errors='replace')


def _frontmost_pid() -> int:
    """PID of the frontmost (focused) application."""
    try:
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        return int(app.processIdentifier()) if app is not None else 0
    except Exception:
        return 0


def _get_foreground_window():
    """
    Return a handle for the focused window.

    On macOS focus belongs to an *application*, not a single window handle,
    so this returns the frontmost application PID. ``WindowGuard`` compares
    PIDs, which is the correct semantics for "is my target app focused?".
    """
    return _frontmost_pid()


def _list_windows() -> list:
    """
    List on-screen top-level windows.

    Each entry mimics the Windows dict::

        {'hwnd': CGWindowNumber, 'title': 'name — owner',
         'class': owner_name, 'pid': owner_pid,
         'owner': owner_name, 'name': window_name}
    """
    windows = []
    options = (Quartz.kCGWindowListOptionOnScreenOnly
               | Quartz.kCGWindowListExcludeDesktopElements)
    try:
        infos = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    except Exception:
        infos = None

    for info in (infos or []):
        try:
            if int(info.get('kCGWindowLayer', 0) or 0) != 0:
                continue  # skip menu bar, dock, overlays
            owner = str(info.get('kCGWindowOwnerName', '') or '')
            name = str(info.get('kCGWindowName', '') or '')
            pid = int(info.get('kCGWindowOwnerPID', 0) or 0)
            number = int(info.get('kCGWindowNumber', 0) or 0)
            if not owner and not name:
                continue
            title = f"{name} — {owner}" if name and owner else (name or owner)
            windows.append({
                'hwnd': number,
                'title': title,
                'class': owner,
                'pid': pid,
                'owner': owner,
                'name': name,
            })
        except (TypeError, ValueError):
            continue

    return windows


def _window_title(hwnd) -> str:
    for w in _list_windows():
        if w['hwnd'] == hwnd:
            return w['title']
    return ''


def _window_class(hwnd) -> str:
    for w in _list_windows():
        if w['hwnd'] == hwnd:
            return w['class']
    return ''


def _window_pid(hwnd) -> int:
    for w in _list_windows():
        if w['hwnd'] == hwnd:
            return w['pid']
    return 0


def _window_thread_id(hwnd) -> int:
    # macOS has no per-window UI thread id exposed here; PID is sufficient.
    return _window_pid(hwnd)


# Friendly app-name aliases. macOS reports the VS Code window owner as
# "Code", so "--target-window 'Visual Studio Code'" must still match it.
_OWNER_ALIASES = {
    'visual studio code': ('visual studio code', 'code'),
    'vs code': ('code',),
    'vscode': ('code',),
    'microsoft excel': ('microsoft excel', 'excel'),
    'excel': ('microsoft excel', 'excel'),
    'libreoffice calc': ('libreoffice', 'soffice'),
    'google chrome': ('google chrome', 'chrome'),
}


def find_windows(pattern: str, exact: bool = False) -> list:
    """
    Find visible windows whose title/owner matches ``pattern``.

    Substring match is case-insensitive by default, so
    ``--target-window "Visual Studio Code"`` matches the owner name even when
    the window title itself is unreadable without Screen Recording permission.
    """
    if not pattern:
        return []
    if exact:
        return [w for w in _list_windows()
                if w['title'] == pattern or w['class'] == pattern]

    needle = pattern.casefold()
    aliases = _OWNER_ALIASES.get(needle, (needle,))
    matches = []
    for w in _list_windows():
        title = w['title'].casefold()
        owner = w['class'].casefold()
        if needle in title or any(alias in owner for alias in aliases):
            matches.append(w)
    return matches


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # process exists but belongs to another user
    except OSError:
        return False


def _focus_window(hwnd, pid: int = None) -> bool:
    """
    Bring the application that owns ``hwnd`` to the foreground and verify it.
    """
    if pid is None:
        pid = _window_pid(hwnd)
    if not pid:
        return False
    if _frontmost_pid() == pid:
        return True
    try:
        app = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app is None:
            return False
        app.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.2)
        return _frontmost_pid() == pid
    except Exception:
        return False


def _is_process_elevated(pid: int) -> bool:
    """True if the process runs as root (macOS equivalent of elevated)."""
    if not pid:
        return False
    try:
        out = subprocess.check_output(
            ['ps', '-o', 'uid=', '-p', str(pid)],
            stderr=subprocess.DEVNULL, text=True,
        ).strip()
        return out == '0'
    except Exception:
        return False


def _is_self_elevated() -> bool:
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


# ──────────────────────────────────────────────
#  Window guard
# ──────────────────────────────────────────────

class WindowGuard:
    """
    Pins the typer to one application window and refuses to type elsewhere.

    On macOS "focus" is application-level, so the guard tracks the target
    application PID and compares it with the frontmost PID. A specific window
    number is stored for reporting and elevation checks.
    """

    def __init__(self, pattern: str, exact: bool = False,
                 refocus: bool = True, finder=None):
        self.pattern = pattern
        self.exact = exact
        self.refocus = refocus
        self.finder = finder or find_windows
        self.hwnd = None
        self.title = ''
        self.pid = 0
        self.refocus_events = 0

    # ── discovery ──
    def resolve(self) -> bool:
        matches = self.finder(self.pattern, exact=self.exact)

        if not matches:
            print(f"\n  [FOCUS] No visible window matches --target-window "
                  f"{self.pattern!r}")
            self._print_candidates()
            return False

        if len(matches) > 1:
            fg = _get_foreground_window()
            chosen = next((w for w in matches if w['pid'] == fg), matches[0])
            print(f"\n  [FOCUS] {len(matches)} windows match "
                  f"{self.pattern!r} — using the "
                  f"{'focused' if chosen['pid'] == fg else 'first'} one:")
            for w in matches:
                mark = '→' if w['hwnd'] == chosen['hwnd'] else ' '
                print(f"    {mark} {_safe_text(w['title'])}")
            print(f"      Narrow the pattern if this is not the right window.")
        else:
            chosen = matches[0]

        self.hwnd = chosen['hwnd']
        self.title = chosen['title']
        self.pid = chosen['pid']

        if not _pid_alive(self.pid):
            print(f"  [FOCUS] Target window vanished before typing started.")
            return False

        print(f"  [FOCUS] Locked onto: {_safe_text(self.title)}")
        print(f"          owner={chosen['class']}  pid={self.pid}")

        if _is_process_elevated(self.pid) and not _is_self_elevated():
            print("\n  [FOCUS] ERROR: the target application runs as root "
                  "but this script does not.")
            print("          macOS may block synthetic input across that boundary.")
            print("          Fix: run this script with the same user, or target "
                  "a normal app.")
            return False

        return True

    def _print_candidates(self):
        candidates = [w for w in _list_windows() if w['title'].strip()]
        if not candidates:
            return
        print("          Visible windows right now:")
        seen = set()
        shown = 0
        for w in candidates:
            key = (w['class'], w['name'])
            if key in seen:
                continue
            seen.add(key)
            print(f"            - {_safe_text(w['title'])}")
            shown += 1
            if shown >= 15:
                break

    # ── focus enforcement ──
    def alive(self) -> bool:
        return self.pid != 0 and _pid_alive(self.pid)

    def ensure_focus(self, attempts: int = 3, stop_event=None) -> bool:
        if not self.alive():
            print("  [FOCUS] Target application is gone (closed or crashed).")
            return False
        if _get_foreground_window() == self.pid:
            return True
        if not self.refocus:
            return True

        for attempt in range(attempts):
            _focus_window(self.hwnd, self.pid)
            time.sleep(0.15 + attempt * 0.10)
            if _get_foreground_window() == self.pid:
                if attempt:
                    self.refocus_events += 1
                return True

        print(f"  [FOCUS] Could not focus {_safe_text(self.title)!r}. "
              f"Click it once, then let the run continue.")
        return False

    def pause_until_focused(self, stop_event=None) -> bool:
        """Pause while the target app is unfocused; resume when it returns."""
        if not self.alive():
            return False
        if _get_foreground_window() == self.pid:
            return True
        if not self.refocus:
            return True

        self.refocus_events += 1
        print(f"\n{'⏸ '*18}")
        print(f"  [PAUSED] Window changed — target application lost focus.")
        print(f"  Typing is paused safely. Switch back to resume...")
        print(f"{'⏸ '*18}\n")

        while _get_foreground_window() != self.pid:
            if stop_event is not None and stop_event.is_set():
                return False
            if not self.alive():
                print(f"  [FOCUS] Target application was closed.")
                return False
            time.sleep(0.4)

        print(f"\n{'▶ '*18}")
        print(f"  [RESUMED] Target application is focused! Continuing...")
        print(f"{'▶ '*18}\n")
        time.sleep(0.6)
        return True

    def check(self) -> bool:
        if _get_foreground_window() == self.pid:
            return True
        if not self.refocus:
            return True

        if _focus_window(self.hwnd, self.pid):
            self.refocus_events += 1
            print("\n  [FOCUS] Focus was stolen — target window refocused.")
            return True

        print("\n  [FOCUS] ABORT: focus left the target window and could not "
              "be restored.")
        print("          Stopping this file to avoid typing into the wrong "
              "application.")
        return False

    def summary(self) -> str:
        if self.pid == 0:
            return "no target window"
        return f"{_safe_text(self.title)!r} ({self.refocus_events} refocus events)"
