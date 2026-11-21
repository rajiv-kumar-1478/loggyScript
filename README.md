# Human-Like Typing Simulator & Detection Suite

> **Educational / Research Use Only** — OS-level keystroke and mouse simulation for studying human vs automated input detection.
>
> ⚠️ This tool **does not defeat real detection** — Windows stamps every simulated keystroke as
> synthetic. See [Detection Limits](#-detection-limits--where-this-gets-caught).

Repository: **https://github.com/rajiv-kumar-1478/loggyScript**

---

## 🏁 Quick Start

```powershell
# 1. Clone
git clone https://github.com/rajiv-kumar-1478/loggyScript.git
cd loggyScript

# 2. Install (only needed for human_typer.py / typing_detector.py)
pip install pynput

# 3. Run — type a single file into any focused window (5s to click the window)
python human_typer.py paragraph.txt

# 4. Run — type a whole project into VS Code (dry run first)
$env:PYTHONIOENCODING="utf-8"
python project_typer.py --source "C:\myproject" --target "C:\myproject_typed" --target-window "Visual Studio Code" --dry-run

# 5. Run — record + analyze real typing to see the verdict
python typing_detector.py monitor 30
```

Full details, all flags and examples are below.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `human_typer.py` | Type a single text/file with human-like behavior |
| `project_typer.py` | Type an **entire project folder** into VS Code file-by-file |
| `excel_typer.py` | Type tabular data (CSV/TSV/JSON/Excel) into **Microsoft Excel** cell-by-cell |
| `typing_detector.py` | Record keystrokes and analyze if typing is human or automated |

---

## ⚙️ Requirements

- **OS**: Windows (uses `user32.dll` SendInput API)
- **Python**: 3.8+
- **Dependencies**: `pynput` (needed by `human_typer.py` and `typing_detector.py`)

```powershell
pip install pynput
```

> `project_typer.py` and `excel_typer.py` use **zero external dependencies** — pure `ctypes` for OS-level input.
> `human_typer.py` and `typing_detector.py` require `pynput`.

---

## 🚀 How to Run

### 1. Single File — `human_typer.py`

Type sample code (Fibonacci) into any focused window:

```powershell
python human_typer.py
```

Type a custom file:

```powershell
python human_typer.py "C:\path\to\your\file.py"
```

> You have **5 seconds** to click into the target window (VS Code, Notepad, etc.) before typing starts.

---

### 2. Entire Project Folder — `project_typer.py`

#### Step 1: Open VS Code with the target folder

```powershell
code "C:\myproject_typed"
```

#### Step 2: Dry run (preview files without typing)

```powershell
$env:PYTHONIOENCODING="utf-8"
python project_typer.py --source "C:\myproject" --target "C:\myproject_typed" --dry-run
```

#### Step 3: Run for real

```powershell
$env:PYTHONIOENCODING="utf-8"
python project_typer.py --source "C:\myproject" --target "C:\myproject_typed"
```

#### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--speed 2.0` | Typing speed multiplier (0.5 = slow, 2.0 = fast) | `1.0` |
| `--wpm 75` | Target words-per-minute (approx.; overrides `--speed`) | off |
| `--calibrate rec.json` | Personalise timing from a real `typing_detector.py` recording | off |
| `--resume 10` | Resume from file index #10 (0-based) | auto from saved progress |
| `--confirm` | Ask before typing each file | off |
| `--delay 3.0` | Seconds to wait after opening each file in VS Code | `2.0` |
| `--extensions ".cs,.py"` | Only type files with these extensions | common code files |
| `--skip-dirs "bin,obj"` | Skip these directory names | `bin,obj,.git,.vs,node_modules` |
| `--dry-run` | List files without typing anything | off |
| `--break-interval "45,60"` | Minutes of typing before an idle rest break (random within range) | `45,60` |
| `--break-duration "3,4"` | Minutes to idle during each rest break (random within range) | `3,4` |
| `--no-breaks` | Disable automatic rest breaks | off |
| `--stop 30` | Work for N minutes then cleanly save progress and exit (e.g. 30 min) | off (runs continuously) |
| `--target-window TITLE` | Type **only** into the window whose title contains `TITLE` (case-insensitive). Aborts instead of typing into the wrong window | off |
| `--target-window-exact` | Require an exact title match instead of a substring | off |
| `--no-focus-guard` | With `--target-window`: resolve + elevation-check the window, but don't re-focus it or abort when focus is lost | off |

#### Examples

```powershell
# Fast typing (2x speed)
python project_typer.py --source "C:\myproject" --target "C:\output" --speed 2.0

# Only C# files
python project_typer.py --source "C:\myproject" --target "C:\output" --extensions ".cs,.csproj"

# Resume from file #50 after interruption
python project_typer.py --source "C:\myproject" --target "C:\output" --resume 50

# Confirm each file before typing
python project_typer.py --source "C:\myproject" --target "C:\output" --confirm

# Target ~75 words per minute
python project_typer.py --source "C:\myproject" --target "C:\output" --wpm 75

# Stop automatically after 30 minutes (saves progress to resume later)
python project_typer.py --source "C:\myproject" --target "C:\output" --stop 30

# Personalise rhythm/typos from a real recorded session
python project_typer.py --source "C:\myproject" --target "C:\output" --calibrate typing_recording.json

# Lock typing to one window — aborts rather than typing into another app
python project_typer.py --source "C:\myproject" --target "C:\output" --target-window "Visual Studio Code"
```

---

### 2b. Window targeting — `--target-window`

Without this flag the typer is **blind**: `SendInput` goes to whatever window currently has
focus. A notification, an alt-tab, or a slow VS Code load is enough to send hundreds of lines
into the wrong application. `--target-window` pins the run to one window:

```powershell
# Check the title matches BEFORE committing to a run (dry run resolves it too)
python project_typer.py --source "C:\myproject" --target "C:\myproject_typed" --target-window "Visual Studio Code" --dry-run

# Real run, locked to VS Code
python project_typer.py --source "C:\myproject" --target "C:\myproject_typed" --target-window "Visual Studio Code"
```

What it does at each stage:

| Stage | Behaviour |
|-------|-----------|
| **Startup** | Resolves the title once. No match → prints every visible window title and exits **before typing anything**. Multiple matches → prefers the focused one and lists the rest. |
| **Elevation check** | If the target runs elevated and this script does not, it **exits immediately** — Windows blocks `SendInput` from a normal process to an elevated window, so every keystroke would silently vanish. |
| **Before each file** | Re-focuses the target (handles the `code` CLI opening a different window) and confirms focus actually took. |
| **While typing** | Polls the foreground window every ~20 characters. Focus stolen → re-focus once; if that fails, **abandons the file** instead of typing into the wrong app. |
| **On exit** | Reports the target and how many refocus events occurred. |

Substring matching is the useful default because the real VS Code title is
`file.py - project - Visual Studio Code`. Use `--target-window-exact` when you need a precise
match, and `--no-focus-guard` to keep the startup resolution/elevation check without the
re-focusing behaviour.

---

### 3. Spreadsheet Entry — `excel_typer.py`

Types tabular data from a CSV, TSV, JSON, or Excel file cell-by-cell into Microsoft Excel (or LibreOffice Calc / Google Sheets) with authentic human-like biometrics, key dwell times, and cell navigation.

Like `project_typer.py`, it uses **zero external dependencies** (pure `ctypes` OS-level `SendInput`).

#### Key Features:
- **Full Biometric Humanizer**:
  - **5-Way Typo Simulation**: Realistic mistakes (substitution, doubling, insertion, omission, transposition) with notice delays and backspacing.
  - **Formula Burst Typing**: Fast muscle-memory burst typing for Excel formulas (`=SUM(`, `=AVERAGE(`, `=IF(`, `=VLOOKUP(`) and common status words (`TRUE`, `FALSE`, `Pending`, `Delivered`, `Shipped`).
  - **Cognitive & Distraction Pauses**: Natural thinking hesitations and occasional phone/talking distraction pauses (3.5–8.5s).
  - **Punctuation Pauses**: Natural cadence slowdown on commas, periods, colons, semicolons, and parentheses.
  - **Warm-Up & Rhythm Drift**: Sessions start with realistic warm-up curves and subtle speed drift across rows.
  - **Fatigue Modeling**: Typing speed gradually slows and typo frequency increases over long runs.
  - **OS-Level Mouse Drift**: Natural Bezier curve mouse micro-movements and sheet glancing via Windows `SendInput`.
- **Auto-Pause on Window Change**:
  - If you switch away from Excel (e.g. click command prompt, open browser, Alt-Tab), typing **immediately pauses safely** without losing state or spraying keys.
  - When you click or switch back to Excel, typing **automatically unpauses and resumes** in 1 second!
- **Auto-Resume on Command Restart**:
  - If you close the terminal, abort with `Ctrl+C`, or restart the command (`python excel_typer.py --source ... --destination ...`), the script **automatically detects previous progress** from `excel_typer_progress.json` and resumes from the exact file / row where it stopped.
  - Pass `--fresh` to force a complete restart from File #1 / Row 1.
- **Hands-Free Auto-Launch**:
  - Automatically launches Microsoft Excel on run, brings it to the foreground, selects cell `A1` via `Ctrl+Home`, and starts typing directly.
- **Universal CSV / Spreadsheet Ingestion**:
  - RFC 4180 multiline cells, auto delimiter sniffing (`,`, `;`, `\t`, `|`), auto encoding detection (UTF-8, UTF-8-BOM, UTF-16, CP1252, Latin-1).
- **Excel Grid Navigation**:
  - `Tab` across columns, `Enter` at row end, and `Alt+Enter` for in-cell line breaks.
- **Auto-Save & Ergonomic Rest Breaks**:
  - Auto-saves workbook (`Ctrl+S`) every N rows (`--save-interval 10`).
  - Automatically selects a random work duration between 45–60 minutes, pauses with a live countdown timer to sleep for 3–4 minutes of human rest, resets fatigue, and automatically resumes typing. Pass `--no-breaks` to disable.
- **Configurable Stop Time Limit (`--stop <minutes>`)**:
  - Optional argument: work for N minutes (e.g. `--stop 30` for 30 minutes) and stop automatically.
  - Automatically saves the workbook / active file, writes exact progress to JSON, and exits cleanly.
  - When re-run, automatically resumes right where it left off! If `--stop` is omitted, the script runs continuously.

#### Run Examples:

##### A. Folder-to-Folder Batch Mode (All CSVs / Spreadsheets in a Folder):
```powershell
# 1. Preview all discovered spreadsheet files and data size (Dry Run)
python excel_typer.py --source "C:\source_folder" --destination "C:\dest_folder" --dry-run

# 2. Batch replicate entire folder into destination Excel files file-by-file (auto-resumes if restarted)
python excel_typer.py --source "C:\source_folder" --destination "C:\dest_folder"

# 3. Work for 30 minutes and stop automatically (resumes on next command)
python excel_typer.py --source "C:\source_folder" --destination "C:\dest_folder" --stop 30

# 4. Force start from File #1 from scratch (ignores saved progress)
python excel_typer.py --source "C:\source_folder" --destination "C:\dest_folder" --fresh

# 5. Filter specific extensions (e.g. only CSV files) and confirm each file
python excel_typer.py --source "C:\source_folder" --destination "C:\dest_folder" --extensions .csv --confirm
```

##### B. Single File Mode:
```powershell
# 1. Type source CSV into destination Excel file (auto-creates and opens destination)
python excel_typer.py --source "C:\path\to\data.csv" --destination "C:\path\to\output.xlsx"

# 2. Type with a 30-minute auto-stop limit
python excel_typer.py --source "C:\path\to\data.csv" --destination "C:\path\to\output.xlsx" --stop 30

# 3. Force start from Row 1 from scratch (ignores saved progress)
python excel_typer.py --source "C:\path\to\data.csv" --destination "C:\path\to\output.xlsx" --fresh

# 4. Preview rows, cells, character count, and time estimate (Dry Run)
python excel_typer.py --source "C:\path\to\data.csv" --destination "C:\path\to\output.xlsx" --dry-run

# 5. Test run with built-in sample inventory data (no file needed)
python excel_typer.py --sample

# 6. Type source file into focused Excel window with auto-save every 5 rows
python excel_typer.py --source "C:\path\to\data.csv" --speed 1.5 --save-interval 5
```

---

### 4. Detection System — `typing_detector.py`

#### Record + Analyze in one step (30 seconds):

```powershell
python typing_detector.py monitor 30
```

#### Record only (saves to `typing_recording.json`):

```powershell
python typing_detector.py record 60
```

#### Analyze a saved recording:

```powershell
python typing_detector.py analyze
```

#### Output

```
  VERDICT:      🟢 HUMAN       (or 🟡 SUSPICIOUS, 🔴 AUTOMATED)
  HUMAN SCORE:  78.2%
  CONFIDENCE:   78.2%
```

---

## 🔧 How It Works

### Typing Simulation (OS-Level)

Both keyboard and mouse go through the **Windows kernel input stack** via `ctypes → user32.dll → SendInput()`:

```
Python Script
    ↓
ctypes.windll.user32.SendInput()     ← OS kernel boundary
    ↓
Windows Input Stack (same path as physical hardware)
    ↓
Application (VS Code)
```

#### Keyboard Features
- **Hardware scan codes** (`KEYEVENTF_SCANCODE`) — same codes a physical PS/2 keyboard sends
- **Realistic dwell time** — each key held 35–280ms (per-key log-normal distribution)
- **Shift timing** — Shift presses 15–40ms before the character, releases 10–30ms after
- **Digraph-aware speed** — common pairs like `th`, `er` typed faster; awkward reaches like `zx` slower
- **Finger / hand model** — same-finger bigrams slow, same-hand slightly slower, hand alternation faster
- **Per-key difficulty** — pinky keys, number row and far reaches are slower and held longer
- **Multiple typo types** — substitution, doubling, insertion, omission and transposition, each corrected naturally
- **Fatigue-aware error rate** — typos and thinking pauses increase as the session goes on
- **Warm-up** — a new file starts slower, then settles into the normal rhythm
- **Macro rhythm drift** — overall speed slowly wanders (attention / comfort), as with real typists
- **Burst typing** — common tokens (`public `, `return `, `class `) typed at 2x speed
- **Pauses** — newline, punctuation, brace, word, comment-reading, block-boundary and rare distraction pauses
- **Mouse activity** — occasional drift/scroll/glances so keystroke-only automation is not obvious
- **Calibration** — `--calibrate` copies IKI, dwell, pause and typo statistics from a real recording
- **Target speed** — `--wpm` sets an approximate words-per-minute target

#### Mouse Features
- **Bézier curve paths** — natural arced movements, not straight lines
- **Ease-in-out timing** — accelerates then decelerates (Fitts's Law)
- **Micro-tremor** — 1–3px physiological hand shake per movement step
- **Idle drift** — subtle 2–15px drift while hand rests on mouse
- **Scroll wheel** — OS-level scroll events (reading code)
- **Glance behavior** — cursor visits tabs, scrollbar, line numbers, then returns to editor

### Detection System (8 Features)

| Feature | What it detects |
|---------|----------------|
| Interval Distribution | Skewness & kurtosis — humans are right-skewed |
| Rhythm Regularity | Coefficient of variation — bots are metronomic |
| Digraph Timing | Different key pairs should have different speeds |
| Pause Patterns | Natural thinking pauses vs none or uniform |
| Backspace Usage | Humans use backspace 1–15%; zero = bot signal |
| Dwell Times | How long keys are held — near-zero = simulated |
| Burst Uniformity | Fast segments shouldn't be perfectly uniform |
| Mouse Correlation | No mouse activity = suspicious |

> These 8 features are **statistical only**. They do not inspect the OS's injected-input flag —
> see [Detection Limits](#-detection-limits--where-this-gets-caught) for what this approach
> cannot see and how real detectors catch simulated input.

---

## 🕵️ Detection Limits — Where This Gets Caught

**Short answer: yes, this will be caught — but not by a "kernel hook that checks a flag".**
The realistic answer depends on *which layer* is watching, and the layers catch you for two
completely different reasons.

### The one thing that cannot be hidden

Every event produced by `SendInput` (both `KEYEVENTF_SCANCODE` and `KEYEVENTF_UNICODE` paths
used in `project_typer.py`, and every `pynput` call in `human_typer.py`) is stamped as
**synthetic by the OS itself**. Windows marks injected input and hands that mark to anything
that asks for it. No amount of timing realism, dwell-time modelling or typo simulation changes
this bit — it is set by `win32k` before the event ever reaches the application.

A user-mode low-level keyboard hook (`WH_KEYBOARD_LL`) can read it in one line:

```c
KBDLLHOOKSTRUCT *kb = (KBDLLHOOKSTRUCT *)lParam;
if (kb->flags & LLKHF_INJECTED) {        /* 0x10 — set on every SendInput event */
    /* automated input — no timing analysis needed */
}
```

The same applies to mouse events via `LLMHF_INJECTED` (`0x01`), and to the legacy
`GetMessageExtraInfo()` check, which returns an injected signature
(`0xFF515700`-family) for synthetic messages.

> This is the honest bottom line: **statistical detection is the weak layer, and this tool
> defeats it on purpose** (`--calibrate` literally copies a real human's IKI/dwell/typo
> statistics, so the detector's own features are trained to look human). The *provenance* flag
> is the strong layer, and nothing in this codebase can affect it.

### The software ceiling

Where each layer stands, and whether any change to this repository can move it:

| Detection layer | Status | Why |
|-----------------|--------|-----|
| 8 statistical features (this repo's detector) | ✅ **Already defeated** | `--calibrate` copies real IKI/dwell/pause/typo stats — that is what it is for |
| `LLKHF_INJECTED` | ❌ **Impossible in software** | Set by `win32k` from the event's *route*, not stored anywhere a caller can write |
| Raw Input `hDevice == NULL` | ❌ **Impossible in software** | No device produced the event, so there is no handle to fabricate |
| Kernel device-stack driver | ⚠️ Not software you can ship | Needs EV cert + MS attestation, must pass Secure Boot + HVCI — which blocks exactly this — and is a rootkit; EDR flags it *at load*, which is the detection |
| Real USB HID | ⚠️ Hardware | No flag, real `hDevice` — and still leaves device-arrival logs + VID/PID fingerprints |

**The statistical layer is the only one software can touch, and this tool already beats it.**
Everything above it is a routing or hardware problem, so there is no edit to `project_typer.py`
that changes the outcome. "Undetectable at every level" is not a reachable engineering target —
it requires a signed kernel driver or a physical USB device.

### Which layer catches what

| Layer | What it can see | Catches synthetic input? | Mechanism |
|-------|-----------------|--------------------------|-----------|
| **App-level statistics** (this repo's `typing_detector.py`) | Inter-key intervals, dwell, typos | ⚠️ Weak / bypassable | Timing heuristics — beaten by `--calibrate` |
| **User-mode low-level hook** (`WH_KEYBOARD_LL`) | `KBDLLHOOKSTRUCT.flags` | ✅ **Instant, 100%** | `LLKHF_INJECTED` bit |
| **`GetMessageExtraInfo()`** | Message extra info | ✅ Instant | Injected signature |
| **Raw Input** (`WM_INPUT` / `GetRawInputData`) | `RAWKEYBOARD.hDevice` | ✅ Instant — or silently drops input | Injected events arrive with `hDevice == NULL` |
| **Kernel filter driver on the keyboard stack** (`kbdclass` / `\Device\KeyboardClass0`) | Real hardware IRPs only | ✅ **By absence, not by flag** | Sees *zero* hardware keystrokes while text still appears |
| **Kernel anti-cheat / EDR** (Vanguard, EAC, BattlEye, CrowdStrike) | Device stack + process behaviour | ✅ Blocks or flags | Correlation + behavioural rules |
| **Accessibility / UIA text watcher** | The text buffer itself | ✅ Instant | Content changes with no key events at all |
| **Integrity level (UIPI)** | — | 🚫 Input is **dropped** | Cannot type into elevated windows |

### Why "kernel-level hook" is the *right instinct* but the wrong mechanism

A kernel-mode filter driver attached to the keyboard device stack **never sees `SendInput`
events at all** — injection happens inside `win32k`'s raw input thread, not through the
`\Device\KeyboardClass*` device stack. So a driver at that layer cannot check an "injected"
flag, because the event never arrives.

It catches you the other way around: the driver sees the *genuine hardware* stream (which is
empty), while the application's text buffer keeps growing. **Real keystrokes: none.
Characters delivered: thousands.** That mismatch is conclusive, and it is exactly what
kernel anti-cheat and EDR products correlate.

So:

- **User-mode hook** → catches you by a *flag* on every event.
- **Kernel driver** → catches you by the *absence* of any hardware events behind the text.
- **Both catch you.** Only the evidence differs.

The only input that carries no injected flag is input that originates from physical hardware.
That is a hardware problem, not a software one, and it is out of scope for this project —
using simulated input to satisfy proctored exams, employment assessments, KYC or account
verification is fraud regardless of how realistic the keystrokes look.

### What `typing_detector.py` itself does **not** check

Worth stating plainly, since the tool's own verdict can be misleading:

- ❌ **Not** `LLKHF_INJECTED` — the hook is already installed via `pynput`, so the flag is
  available, but the 8 features are purely statistical and never inspect it.
- ❌ **Not** `GetMessageExtraInfo()` signatures.
- ❌ **Not** Raw Input `hDevice` (whether a physical device produced the event).
- ❌ **Not** UIA/text-buffer correlation.
- ❌ **No ground truth** — it infers "human vs automated" from timing alone, so a careful slow
  human can be scored 🟡/🔴 (false positive) and a calibrated simulator scores 🟢 (false
  negative). Treat the verdict as a *statistical opinion*, not a security control.

### Non-input evidence left behind

Even ignoring input provenance entirely, `project_typer.py` leaves artefacts that a reviewer
can see without any hook at all:

| Artefact | Why it stands out |
|----------|-------------------|
| `.vscode/settings.json` written into the target folder | Direct fingerprint of this script |
| File `mtime`s clustered within a few minutes | A real project takes days/weeks |
| VS Code Local History (`%APPDATA%\Code\User\History`) | Hundreds of near-identical saves in rapid succession |
| Uniform formatting / zero exploratory edits | No debugging churn, no half-written functions |
| Git author timestamps | All commits inside one session |
| Per-character undo stack | Typed content produces hundreds of undo steps; pasted content produces one |

### Where it simply fails to work

1. **Elevated windows** — a normal-integrity process cannot `SendInput` into an admin window;
   the call fails (`ERROR_ACCESS_DENIED`) and nothing is typed.
2. **UAC prompts / secure desktop / lock screen** — input injection is blocked by design.
3. **Focus loss** — anything that steals focus mid-run sends the remaining text to the wrong
   window (or nowhere). This is the most common real-world failure.
4. **Anti-cheat protected games** — Raw Input-only handling drops synthetic events, or the
   anti-cheat blocks the process outright.
5. **EDR / endpoint security** — an unsigned `python.exe` emitting thousands of `SendInput`
   calls per minute is a textbook behavioural signature and may be quarantined.

> **Summary:** this project is a *detection-research* tool, not a bypass tool. It is useful for
> studying how statistical detectors behave and where they fail. It does not defeat provenance
> checks, and it is not intended to be used anywhere input authenticity is being verified.

---

## ⚠️ Important Notes

1. **Do NOT touch keyboard or mouse** while `project_typer.py` is running — it will interfere with the simulated input.
2. **Press `Ctrl+C`** in the terminal to stop at any time. Progress is saved automatically.
3. **Use `--resume N`** to continue from where you left off after stopping.
4. Files larger than **100KB** are automatically skipped (likely generated code).
5. The `PYTHONIOENCODING=utf-8` env variable is needed to avoid Unicode errors in PowerShell.
6. `project_typer.py` writes `.vscode/settings.json` into the target folder to disable auto-indent, auto-closing, suggestions and Emmet. **Keep these settings** — otherwise VS Code corrupts the typed output (extra indentation, accepted completions, lost newlines).
7. Before typing a file that already has content, the script clears the editor (`Ctrl+A`, `Delete`) so a resumed run does not duplicate it.
8. If `--resume` is omitted, saved progress (`project_typer_progress.json`) is used automatically. Pass `--resume 0` to start over.
9. Rest breaks are enforced **during long files too**, not only between files: after a random 30-60 minutes the typer goes idle for a random 3-4 minutes (checked at word/newline boundaries). Tune with `--break-interval`, `--break-duration`, or disable with `--no-breaks`.
10. **Always use `--target-window`** for unattended runs. Without it the typer types into whatever has focus — one notification or alt-tab sends the rest of the file somewhere else. With it, the run aborts rather than misfire.
11. If `--target-window` exits with an elevation error, the target app is running as Administrator and this script is not. Windows blocks synthetic input across that boundary — run both at the same level.

---

## 📂 Generated Files

| File | Created by |
|------|-----------|
| `typing_recording.json` | `typing_detector.py record` — raw keystroke data |
| `analysis_report.json` | `typing_detector.py analyze` — full detection report |
| `project_typer_progress.json` | `project_typer.py` — resume checkpoint |

> `typing_recording.json`, `analysis_report.json` and `project_typer_progress.json` are **local runtime output** — they are committed here as sample data, but you can safely delete them. `project_typer_progress.json` is git-ignored by default.

---

## 📤 Push to GitHub

The remote is already configured in this folder:

```powershell
git remote -v
# origin  https://github.com/rajiv-kumar-1478/loggyScript.git (fetch)
# origin  https://github.com/rajiv-kumar-1478/loggyScript.git (push)
```

### First-time push

```powershell
git add .
git commit -m "docs: add README with run + push instructions"
git branch -M main
git push -u origin main
```

> The GitHub repo was empty, so `main` becomes the default branch. If you prefer `master`, use `git branch -M master` and `git push -u origin master` instead.

### Everyday workflow

```powershell
git status                 # what changed
git add <file>             # stage specific files (or `git add .`)
git commit -m "feat: ..."  # commit with a message
git push                   # upload to GitHub
```

### If authentication is requested

GitHub no longer accepts account passwords over HTTPS. Use either:

1. **Personal Access Token (recommended)**
   - GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic) → *Generate new token* → scope `repo`
   - When prompted: username = your GitHub username, password = the token
   - Cache it once: `git config --global credential.helper manager`

2. **SSH instead of HTTPS**

   ```powershell
   ssh-keygen -t ed25519 -C "your@email.com"
   # add ~/.ssh/id_ed25519.pub to GitHub → Settings → SSH and GPG keys
   git remote set-url origin git@github.com:rajiv-kumar-1478/loggyScript.git
   git push -u origin main
   ```

### Common fixes

| Problem | Fix |
|---------|-----|
| `remote origin already exists` | `git remote set-url origin https://github.com/rajiv-kumar-1478/loggyScript.git` |
| `src refspec main does not match any` | Commit first: `git add . && git commit -m "init"` |
| `Updates were rejected` | `git pull --rebase origin main` then `git push` |
| `LF will be replaced by CRLF` | Harmless on Windows (line-ending warning) |
| `__pycache__` / `.pyc` committed by mistake | `git rm -r --cached __pycache__ *.pyc` then commit |

---

## 📄 License

Educational / research use only. No warranty. Use on your own machine and your own accounts.


