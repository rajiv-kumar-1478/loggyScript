# Human-Like Typing Simulator & Detection Suite

> **Educational / Research Use Only** — OS-level keystroke and mouse simulation for studying human vs automated input detection.

---

## 📁 Files

| File | Purpose |
|------|---------|
| `human_typer.py` | Type a single text/file with human-like behavior |
| `project_typer.py` | Type an **entire project folder** into VS Code file-by-file |
| `typing_detector.py` | Record keystrokes and analyze if typing is human or automated |

---

## ⚙️ Requirements

- **OS**: Windows (uses `user32.dll` SendInput API)
- **Python**: 3.8+
- **Dependencies**: `pynput` (needed by `human_typer.py` and `typing_detector.py`)

```powershell
pip install pynput
```

> `project_typer.py` uses **zero external dependencies** — pure `ctypes` for OS-level input.
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
code "C:\Users\rk170\Desktop\unsecureAPI_typed"
```

#### Step 2: Dry run (preview files without typing)

```powershell
$env:PYTHONIOENCODING="utf-8"
python project_typer.py --source "C:\Users\rk170\Desktop\unsecureAPI project" --target "C:\Users\rk170\Desktop\unsecureAPI_typed" --dry-run
```

#### Step 3: Run for real

```powershell
$env:PYTHONIOENCODING="utf-8"
python project_typer.py --source "C:\Users\rk170\Desktop\unsecureAPI project" --target "C:\Users\rk170\Desktop\unsecureAPI_typed"
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
| `--break-interval "30,60"` | Minutes of typing before an idle rest break (random within range) | `30,60` |
| `--break-duration "3,4"` | Minutes to idle during each rest break (random within range) | `3,4` |
| `--no-breaks` | Disable automatic rest breaks | off |

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

# Personalise rhythm/typos from a real recorded session
python project_typer.py --source "C:\myproject" --target "C:\output" --calibrate typing_recording.json
```

---

### 3. Detection System — `typing_detector.py`

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

---

## 📂 Generated Files

| File | Created by |
|------|-----------|
| `typing_recording.json` | `typing_detector.py record` — raw keystroke data |
| `analysis_report.json` | `typing_detector.py analyze` — full detection report |
| `project_typer_progress.json` | `project_typer.py` — resume checkpoint |











 $env:PYTHONIOENCODING="utf-8"; python "C:\Users\rk170\Desktop\__pycache__\project_typer.py" --source "C:\Users\rk170\Desktop\unsecureAPI project" --target "C:\Users\rk170\Desktop\unsecureAPI_typed"
