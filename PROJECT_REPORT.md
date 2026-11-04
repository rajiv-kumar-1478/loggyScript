# Detailed Component & Architecture Report

This repository contains a biometric input simulation and detection research suite designed for Windows systems. It investigates the physiological, cognitive, and physical mechanics distinguishing human keystrokes from automated input.

---

## 1. `project_typer.py` — OS-Level Project-Scale Input Simulator

### 1.1 Overview & Purpose
`project_typer.py` is the primary automation engine. It replicates entire project directory structures into a target workspace using a live VS Code instance, typing each file character-by-character while matching human biometric parameters. It requires zero external Python dependencies, interfacing directly with the Windows kernel via `ctypes`.

### 1.2 Core Architectural Components

- **OS-Level Windows API Input (`SendInput`)**:
  - Implements `user32.dll` `SendInput` using C-compatible `ctypes.Structure` unions (`INPUT`, `KEYBDINPUT`, `MOUSEINPUT`).
  - Utilizes PS/2 hardware scan codes (`KEYEVENTF_SCANCODE`) via a hardware scan code mapping table (`VK_TO_SCAN`). Keystrokes pass through the Windows raw input architecture identical to a physical USB/PS2 keyboard, evading software-level synthetic input flags (`LLKHF_INJECTED`).
  - Provides fallback Unicode input (`KEYEVENTF_UNICODE`) for extended multi-byte or non-ASCII characters.

- **Realistic Dwell Time & Inter-Key Interval (IKI)**:
  - Models key dwell time (time key remains physically depressed) using a right-skewed log-normal distribution:
    $$\mu \approx \ln(0.085),\ \sigma \approx 0.3 \implies 40\text{ ms} \le t_{\text{dwell}} \le 250\text{ ms}$$
  - Dynamic Shift key sequencing: Shift scan codes are pressed 15–40 ms prior to character keydown and released 10–30 ms post-release, reproducing physical human hand mechanics.

- **Kinematic Mouse Movement Engine**:
  - Generates natural, human-like mouse paths using Cubic Bézier Curves:
    $$B(t) = (1-t)^3 P_0 + 3(1-t)^2 t P_1 + 3(1-t)t^2 P_2 + t^3 P_3, \quad t \in [0, 1]$$
  - Velocity profile governed by Fitts's Law ease-in-out curve to simulate biological muscle acceleration and deceleration.
  - Adds per-step Gaussian micro-tremors (1–3 px) and background hand drift (2–15 px) to match live human resting hand tremor.
  - Implements spontaneous glance gestures (briefly inspecting tabs, explorer panel, or scrollbar) and wheel scrolling.

- **Typo Modeling & Error Correction**:
  - Simulates 5 distinct cognitive and motor typo categories:
    1. *Neighbor Substitution*: Fat-finger hit on an adjacent QWERTY key.
    2. *Doubling*: Premature repeated strike.
    3. *Insertion*: Involuntary extra key stroke.
    4. *Omission*: Skipping a letter during rapid execution.
    5. *Transposition*: Reversing two sequential letters during fast digraph transitions.
  - Generates realistic realization delays (80–350 ms) before triggering corrective backspaces.

- **Cognitive Pauses, Rest Breaks & Fatigue**:
  - Distributes cognitive pauses across lexical and syntactic boundaries (newlines, commas, parentheses, colons).
  - Enforces periodic biological rest breaks (random 3–4 minutes every 30–60 minutes of active typing).
  - Progressive fatigue curve slightly slows base IKI and marginally increases typo probability as session character counts increase.

- **Calibration & Checkpointing**:
  - `--calibrate <file.json>`: Extracts IKI distributions, mean dwell times, pause rates, and error frequencies from real recorded keystroke sessions (`typing_recording.json`).
  - Progress persistence: Automatically saves resume checkpoints (`project_typer_progress.json`) enabling seamless resumption (`--resume`) without duplicating code.

---

## 2. `typing_detector.py` — Biometric Input Detection & Analysis Suite

### 2.1 Overview & Purpose
`typing_detector.py` is a forensic analysis and real-time monitoring suite that evaluates keyboard and mouse event streams to distinguish human typists from programmatic scripts and macro replays.

### 2.2 8-Feature Detection Heuristics

| # | Heuristic Feature | Mathematical / Analytical Metric | Expected Human Baseline |
|---|-------------------|-----------------------------------|-------------------------|
| 1 | **Interval Distribution** | Skewness ($\gamma_1$) and Kurtosis ($\beta_2$) of Inter-Key Intervals (IKI) | Positively skewed ($\gamma_1 > 1.5$), leptokurtic heavy tail ($\beta_2 > 3.0$), log-normal fit. |
| 2 | **Rhythm Regularity** | Coefficient of Variation ($CV = \frac{\sigma}{\mu}$) | $CV \ge 0.45$; automated scripts exhibit low CV or uniform distributions. |
| 3 | **Digraph Timing Variance** | Relative variance across distinct 2-character sequences | High variance (common digraphs like `th`, `er` are fast; awkward reaches like `zx` are slow). |
| 4 | **Pause Patterns** | Frequency and location of pauses $> 300\text{ ms}$ | Clustered around syntax landmarks (punctuation, line terminators). |
| 5 | **Backspace & Correction** | Backspace / Total keystrokes ratio | $1\% \le \text{Ratio} \le 15\%$; $0\%$ is a strong indicator of automation. |
| 6 | **Dwell Time Analysis** | Duration of key depression ($t_{\text{up}} - t_{\text{down}}$) | $40\text{ ms} \le t_{\text{dwell}} \le 200\text{ ms}$; synthetic inputs typically show near-zero or static dwell. |
| 7 | **Burst Uniformity** | Variance within local rolling windows | Natural micro-acceleration bursts on familiar words with non-zero entropy. |
| 8 | **Mouse Activity Correlation** | Keystroke-to-mouse temporal interleaving | Concurrent micro-movements, scrolling, and cursor shifts. |

### 2.3 Scoring & Classification Engine
- Computes weighted feature scores and maps them into a normalized composite human probability score:
  - **HUMAN** ($\ge 75\%$ score): Natural biological variance present across all key metrics.
  - **SUSPICIOUS** ($50\% - 74\%$ score): Exhibits partial human characteristics but reveals statistical anomalies (e.g., uniform digraph timing or zero backspaces).
  - **AUTOMATED** ($< 50\%$ score): Demonstrates metronomic consistency, near-zero dwell times, or robotic timing.

---

## 3. `human_typer.py` — Single-File Typing Simulator

### 3.1 Overview & Purpose
A lightweight, dependency-driven (`pynput`) simulator tailored for individual files, code snippets, or live clipboard demonstrations.

### 3.2 Key Capabilities
- `TypingProfile` configurable model for base delays, burst tokens (`def `, `return `, `class `), and QWERTY adjacency graphs.
- Simulates natural syntax pauses and right-skewed log-normal key delays.
- Integrates mouse jitter to introduce concurrent cursor entropy.
- Serves as the rapid-testing prototyping bed for typing mechanics prior to full-project execution.

---

## 4. Supporting Data & Artifacts

- **`typing_recording.json`**: Real-world recorded keystroke and mouse event dataset containing 4,400+ timestamped events. Provides the statistical ground truth for calibrating simulator parameters and benchmarking detector classifiers.
- **`analysis_report.json`**: Structured JSON report generated by `typing_detector.py analyze`, documenting distribution metrics, digraph variances, pause counts, and final classification verdicts.
- **`paragraph.txt`**: Standardized text fixture used for baseline recording and manual typing verification.
- **`README.md`**: User-facing manual containing complete execution workflows, PowerShell parameter tables, and architectural diagrams.
