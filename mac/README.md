# macOS build — `project_typer.py` + `excel_typer.py`

These are the macOS ports of the two Windows typing simulators. **Every
command-line argument is identical to the Windows versions** — you can take any
command from the main README and run it here unchanged (only the paths change).

```
mac/
├── mac_input.py      # macOS platform layer (Quartz / CoreGraphics)
├── project_typer.py  # same CLI as ../project_typer.py
├── excel_typer.py    # same CLI as ../excel_typer.py
└── requirements.txt
```

---

## 1. Requirements

* macOS 11 or newer
* Python 3.9+
* `pyobjc` (Quartz + Cocoa) — this replaces the Windows `user32.dll` / `SendInput` layer
* `openpyxl` — optional, only for reading/writing `.xlsx` files

```bash
python3 -m pip install -r mac/requirements.txt
```

Run everything from the repository root (or from inside `mac/`), for example:

```bash
python3 mac/project_typer.py --source "/Users/me/src" --target "/Users/me/typed"
python3 mac/excel_typer.py  --source "/Users/me/data.csv" --destination "/Users/me/output.xlsx"
```

---

## 2. Grant permissions (required)

macOS silently drops synthetic keystrokes unless the app that owns your
terminal is trusted. Both scripts check this at startup and print a warning.

1. **Accessibility** — `System Settings → Privacy & Security → Accessibility`
   * Add and enable **Terminal**, **iTerm2**, or **Visual Studio Code**
     (whichever app you run Python from).
2. **Screen Recording** *(optional)* — `System Settings → Privacy & Security →
   Screen Recording`
   * Needed only if you want `--target-window` to match on **window titles**.
   * Without it, matching still works on the **application name**
     (`Visual Studio Code`, `Microsoft Excel`, ...), which is enough for the
     documented examples.

After changing permissions, **restart the terminal** so the new trust takes
effect.

---

## 3. What changed vs. Windows

The typing engines, timing model, typo engine, breaks, resume files and all
flags are untouched. Only the OS boundary and the Mac shortcut keys changed:

| Area | Windows | macOS |
|------|---------|-------|
| Input API | `SendInput` (`user32.dll`) | `CGEventPost` (Quartz / CoreGraphics) |
| Save | `Ctrl+S` | `Cmd+S` |
| Select all / clear | `Ctrl+A` | `Cmd+A` |
| Close tab / workbook | `Ctrl+W` | `Cmd+W` |
| Excel go to A1 | `Ctrl+Home` | `Ctrl+Home` |
| Excel in-cell newline | `Alt+Enter` | `Ctrl+Option+Return` |
| Focus target | window handle | frontmost **application** PID |
| Window titles | always readable | need Screen Recording; app name always readable |

Other behaviour is unchanged: `--dry-run`, `--speed`, `--wpm`, `--calibrate`,
`--extensions`, `--skip-dirs`, `--delay`, `--resume`, `--confirm`,
`--break-interval`, `--break-duration`, `--no-breaks`, `--stop`,
`--target-window`, `--target-window-exact`, `--no-focus-guard`,
`--nav-mode`, `--start-row`, `--start-col`, `--max-rows`, `--save-interval`,
`--sample`, `--delimiter`, `--encoding`, `--no-pad`, `--strip`, `--fresh`.

---

## 4. Quick start

### Project typer

```bash
# 1. Dry run — list files, no typing
python3 mac/project_typer.py \
  --source "/Users/me/src" --target "/Users/me/typed" --dry-run

# 2. Real run, locked to VS Code
python3 mac/project_typer.py \
  --source "/Users/me/src" --target "/Users/me/typed" \
  --target-window "Visual Studio Code"

# 3. Faster + stop after 30 minutes (auto-resumes next run)
python3 mac/project_typer.py \
  --source "/Users/me/src" --target "/Users/me/typed" \
  --target-window "Visual Studio Code" --speed 2.0 --stop 30
```

> Open the target folder in VS Code first (`code "/Users/me/typed"`). The
> script writes `.vscode/settings.json` into the target to disable auto-indent,
> auto-closing and suggestions so the typed output is not corrupted.

### Excel typer

```bash
# 1. Dry run — rows, cells, characters, estimated time
python3 mac/excel_typer.py \
  --source "/Users/me/data.csv" --destination "/Users/me/output.xlsx" --dry-run

# 2. Type the CSV into a spreadsheet
python3 mac/excel_typer.py \
  --source "/Users/me/data.csv" --destination "/Users/me/output.xlsx"

# 3. Folder-to-folder batch mode
python3 mac/excel_typer.py \
  --source "/Users/me/sheets" --destination "/Users/me/sheets_typed"

# 4. Built-in sample inventory (no input file)
python3 mac/excel_typer.py --sample
```

The script launches the first installed spreadsheet app it finds:
**Microsoft Excel → Numbers → LibreOffice**, then falls back to the default
handler for the file extension. Cell `A1` is selected with `Ctrl+Home`.

---

## 5. Notes & limitations

* **US keyboard layout assumed.** Physical key codes are used for realistic
  dwell/shift timing. Characters that have no key code (accented letters,
  emoji, CJK) fall back to Unicode injection and are layout-independent.
* **Secure Input** (some password fields, 1Password, etc.) blocks synthetic
  input by design. Use `--target-window` so the run aborts instead of spraying.
* **Minimised windows** are not listed (the window list is on-screen only).
  Restore the target window before starting.
* **Elevation** on macOS means running as root. If the target app is root and
  the script is not, the guard refuses to type — mirroring the Windows UAC
  check.
* **Do not touch the keyboard/mouse** during a run; the simulated input shares
  the same event stream.
* Progress files keep the same names (`project_typer_progress.json`,
  `excel_typer_progress.json`) and the same resume semantics, so `--fresh`
  and `--resume` behave exactly as documented.

---

## Educational / research use only

This is a detection-research tool. macOS marks synthetic events at the OS
level and Accessibility/EDR tooling can identify them. Do not use it where
input authenticity is being verified (exams, assessments, KYC, account
verification). See the main README for the full detection-limits discussion.
