"""
Typing Behavior Detector & Verifier
=====================================
Monitors and records keystroke events, then analyzes them
to classify typing as HUMAN or AUTOMATED/SYNTHETIC.

Detection features analyzed:
  1. Inter-key interval distribution (mean, std, skewness, kurtosis)
  2. Digraph timing patterns (common vs uncommon pairs)
  3. Typing rhythm regularity (coefficient of variation)
  4. Burst detection (sustained high-speed typing segments)
  5. Pause pattern analysis (natural thinking pauses)
  6. Typo & correction detection (backspace patterns)
  7. Timing distribution shape (KS test against human baselines)
  8. Mouse activity correlation

Usage:
  Phase 1 — Record:  python typing_detector.py record
  Phase 2 — Analyze: python typing_detector.py analyze
  Combined:          python typing_detector.py monitor

WARNING: This is for educational / research purposes only.
"""

import time
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

try:
    from pynput import keyboard, mouse
except ImportError:
    print("ERROR: pynput is required. Install it with:")
    print("  pip install pynput")
    exit(1)


# ──────────────────────────────────────────────
#  Keystroke Event Recorder
# ──────────────────────────────────────────────

class KeystrokeRecorder:
    """Records raw keystroke events with precise timestamps."""

    def __init__(self):
        self.events = []             # List of (timestamp, event_type, key_char)
        self.mouse_events = []       # List of (timestamp, x, y, event_type)
        self._recording = False
        self._kb_listener = None
        self._mouse_listener = None
        self._start_time = None

    def _on_key_press(self, key):
        if not self._recording:
            return
        ts = time.perf_counter() - self._start_time
        char = self._key_to_char(key)
        self.events.append({
            'timestamp': ts,
            'event': 'press',
            'key': char,
            'raw': str(key),
        })

    def _on_key_release(self, key):
        if not self._recording:
            return
        ts = time.perf_counter() - self._start_time
        char = self._key_to_char(key)
        self.events.append({
            'timestamp': ts,
            'event': 'release',
            'key': char,
            'raw': str(key),
        })

        # Stop recording on Escape
        if key == keyboard.Key.esc:
            self._recording = False
            return False

    def _on_mouse_move(self, x, y):
        if not self._recording:
            return
        ts = time.perf_counter() - self._start_time
        self.mouse_events.append({
            'timestamp': ts,
            'x': x,
            'y': y,
            'event': 'move',
        })

    def _on_mouse_click(self, x, y, button, pressed):
        if not self._recording:
            return
        ts = time.perf_counter() - self._start_time
        self.mouse_events.append({
            'timestamp': ts,
            'x': x,
            'y': y,
            'event': 'click' if pressed else 'release',
            'button': str(button),
        })

    def _key_to_char(self, key):
        """Convert pynput key to a readable character string."""
        try:
            return key.char if key.char else str(key)
        except AttributeError:
            return str(key)

    def start_recording(self, duration_seconds: float = 60.0):
        """
        Record keystrokes and mouse events for a given duration.
        Press Escape to stop early.
        """
        self.events = []
        self.mouse_events = []
        self._recording = True
        self._start_time = time.perf_counter()

        print(f"\n{'='*50}")
        print(f"  RECORDING — Type naturally for {duration_seconds:.0f}s")
        print(f"  Press ESC to stop recording early")
        print(f"{'='*50}\n")

        self._kb_listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._mouse_listener = mouse.Listener(
            on_move=self._on_mouse_move,
            on_click=self._on_mouse_click,
        )

        self._kb_listener.start()
        self._mouse_listener.start()

        try:
            start = time.time()
            while self._recording and (time.time() - start) < duration_seconds:
                time.sleep(0.1)
        except KeyboardInterrupt:
            pass

        self._recording = False
        self._kb_listener.stop()
        self._mouse_listener.stop()

        print(f"\n[Recording stopped] Captured {len(self.events)} keyboard events, "
              f"{len(self.mouse_events)} mouse events.")

    def save_recording(self, filepath: str):
        """Save the recorded events to a JSON file."""
        data = {
            'recorded_at': datetime.now().isoformat(),
            'keyboard_events': self.events,
            'mouse_events': self.mouse_events,
            'total_keyboard_events': len(self.events),
            'total_mouse_events': len(self.mouse_events),
        }
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        print(f"[Saved] Recording saved to: {filepath}")

    @staticmethod
    def load_recording(filepath: str) -> dict:
        """Load a previously saved recording."""
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)


# ──────────────────────────────────────────────
#  Typing Behavior Analyzer
# ──────────────────────────────────────────────

class TypingAnalyzer:
    """
    Analyzes recorded keystroke data and produces a
    HUMAN vs AUTOMATED classification with confidence scores.
    """

    # Thresholds calibrated against typical human typing
    THRESHOLDS = {
        'min_cv_for_human': 0.35,           # Coefficient of variation — humans > 0.35
        'max_cv_for_bot': 0.25,             # Bots typically < 0.25
        'min_skewness_for_human': 0.3,      # Humans have right-skewed distributions
        'backspace_ratio_human_min': 0.01,  # Humans use backspace at least 1%
        'backspace_ratio_human_max': 0.15,  # But not more than 15%
        'pause_ratio_min': 0.02,            # Humans have pauses (>500ms) at least 2% of time
        'digraph_variance_min': 0.003,      # Variance of digraph-specific timings
        'burst_uniformity_max': 0.15,       # Burst segments shouldn't be too uniform
        'dwell_time_human_range': (0.05, 0.20),  # Typical human key dwell time
    }

    def __init__(self, keyboard_events: list, mouse_events: list = None):
        self.events = keyboard_events
        self.mouse_events = mouse_events or []
        self.scores = {}  # Feature name -> (score 0-1, weight, detail)

    def analyze(self) -> dict:
        """Run all analysis features and return classification result."""
        press_events = [e for e in self.events if e['event'] == 'press']

        if len(press_events) < 10:
            return {
                'classification': 'INSUFFICIENT_DATA',
                'confidence': 0,
                'detail': 'Need at least 10 keypress events for analysis.',
            }

        # Extract inter-key intervals (flight times)
        intervals = []
        for i in range(1, len(press_events)):
            dt = press_events[i]['timestamp'] - press_events[i-1]['timestamp']
            if dt < 5.0:  # Ignore gaps > 5s (probably window switch)
                intervals.append(dt)

        if len(intervals) < 5:
            return {
                'classification': 'INSUFFICIENT_DATA',
                'confidence': 0,
                'detail': 'Not enough consecutive keystrokes.',
            }

        # Run each detection feature
        self._analyze_interval_distribution(intervals)
        self._analyze_rhythm_regularity(intervals)
        self._analyze_digraph_timing(press_events)
        self._analyze_pause_patterns(intervals)
        self._analyze_backspace_usage(press_events)
        self._analyze_dwell_times()
        self._analyze_burst_uniformity(intervals)
        self._analyze_mouse_correlation(press_events)

        # Aggregate scores
        return self._compute_verdict()

    def _analyze_interval_distribution(self, intervals: list):
        """Check if inter-key interval distribution matches human patterns."""
        mean_iki = sum(intervals) / len(intervals)
        variance = sum((x - mean_iki) ** 2 for x in intervals) / len(intervals)
        std_iki = math.sqrt(variance)

        # Skewness — humans have right-skewed distributions
        if std_iki > 0:
            skewness = sum(((x - mean_iki) / std_iki) ** 3 for x in intervals) / len(intervals)
        else:
            skewness = 0

        # Kurtosis — humans have heavier tails than uniform
        if std_iki > 0:
            kurtosis = sum(((x - mean_iki) / std_iki) ** 4 for x in intervals) / len(intervals) - 3
        else:
            kurtosis = 0

        score = 0.0
        details = []

        # Human typing is right-skewed (many fast keys, some slow pauses)
        if skewness > self.THRESHOLDS['min_skewness_for_human']:
            score += 0.4
            details.append(f"Right-skewed distribution (skew={skewness:.2f}) ✓")
        else:
            details.append(f"Low skewness (skew={skewness:.2f}) — suspicious ✗")

        # Kurtosis — humans have leptokurtic distribution (heavy tails)
        if kurtosis > 0.5:
            score += 0.3
            details.append(f"Heavy-tailed distribution (kurtosis={kurtosis:.2f}) ✓")
        else:
            details.append(f"Light tails (kurtosis={kurtosis:.2f}) — suspicious ✗")

        # Mean IKI should be in human range
        if 0.05 < mean_iki < 0.5:
            score += 0.3
            details.append(f"Mean IKI in human range ({mean_iki*1000:.0f}ms) ✓")
        else:
            details.append(f"Mean IKI unusual ({mean_iki*1000:.0f}ms) ✗")

        self.scores['interval_distribution'] = (score, 1.5, {
            'mean_iki_ms': mean_iki * 1000,
            'std_iki_ms': std_iki * 1000,
            'skewness': skewness,
            'kurtosis': kurtosis,
            'details': details,
        })

    def _analyze_rhythm_regularity(self, intervals: list):
        """
        Coefficient of Variation (CV) — the ratio of std to mean.
        Humans have high CV (irregular rhythm). Bots have low CV (metronomic).
        """
        mean_iki = sum(intervals) / len(intervals)
        std_iki = math.sqrt(sum((x - mean_iki) ** 2 for x in intervals) / len(intervals))
        cv = std_iki / mean_iki if mean_iki > 0 else 0

        score = 0.0
        details = []

        if cv > self.THRESHOLDS['min_cv_for_human']:
            score = 1.0
            details.append(f"High rhythm variability (CV={cv:.3f}) ✓ — looks human")
        elif cv > self.THRESHOLDS['max_cv_for_bot']:
            score = 0.5
            details.append(f"Moderate rhythm variability (CV={cv:.3f}) — borderline")
        else:
            score = 0.0
            details.append(f"Very regular rhythm (CV={cv:.3f}) ✗ — looks automated")

        self.scores['rhythm_regularity'] = (score, 2.0, {
            'coefficient_of_variation': cv,
            'details': details,
        })

    def _analyze_digraph_timing(self, press_events: list):
        """
        Analyze timing patterns for specific key pairs (digraphs).
        Humans have consistent digraph-specific speeds that vary between digraphs.
        Bots tend to have uniform timing regardless of key pair.
        """
        digraph_times = defaultdict(list)

        for i in range(1, len(press_events)):
            dt = press_events[i]['timestamp'] - press_events[i-1]['timestamp']
            if dt > 2.0:
                continue
            pair = press_events[i-1]['key'] + press_events[i]['key']
            if len(pair) == 2 and pair[0].isalpha() and pair[1].isalpha():
                digraph_times[pair.lower()].append(dt)

        # Calculate mean timing per digraph
        digraph_means = {}
        for pair, times in digraph_times.items():
            if len(times) >= 2:  # Need at least 2 samples
                digraph_means[pair] = sum(times) / len(times)

        score = 0.0
        details = []

        if len(digraph_means) >= 3:
            # Variance across digraph means — humans show different speeds for different pairs
            all_means = list(digraph_means.values())
            grand_mean = sum(all_means) / len(all_means)
            between_variance = sum((m - grand_mean) ** 2 for m in all_means) / len(all_means)

            if between_variance > self.THRESHOLDS['digraph_variance_min']:
                score = 1.0
                details.append(f"High digraph timing variance ({between_variance:.4f}) ✓ — human-like")
            else:
                score = 0.2
                details.append(f"Low digraph timing variance ({between_variance:.4f}) ✗ — uniform timing")

            # Show top 5 fastest and slowest digraphs
            sorted_digraphs = sorted(digraph_means.items(), key=lambda x: x[1])
            fastest = sorted_digraphs[:3]
            slowest = sorted_digraphs[-3:]
            details.append(f"Fastest digraphs: {[(p, f'{t*1000:.0f}ms') for p,t in fastest]}")
            details.append(f"Slowest digraphs: {[(p, f'{t*1000:.0f}ms') for p,t in slowest]}")
        else:
            score = 0.5
            details.append("Insufficient digraph data for analysis")

        self.scores['digraph_timing'] = (score, 1.5, {
            'unique_digraphs_analyzed': len(digraph_means),
            'details': details,
        })

    def _analyze_pause_patterns(self, intervals: list):
        """
        Humans have natural pauses (thinking, reading, planning).
        Bots either have no pauses or synthetic uniform pauses.
        """
        pause_threshold = 0.5  # 500ms = a "pause"
        pauses = [x for x in intervals if x > pause_threshold]
        pause_ratio = len(pauses) / len(intervals) if intervals else 0

        score = 0.0
        details = []

        if pause_ratio >= self.THRESHOLDS['pause_ratio_min']:
            score += 0.5
            details.append(f"Natural thinking pauses detected ({pause_ratio*100:.1f}%) ✓")
        else:
            details.append(f"Very few pauses ({pause_ratio*100:.1f}%) ✗ — suspicious")

        # Check if pauses occur at natural positions (after analysis of surrounding keys)
        if len(pauses) >= 2:
            pause_std = math.sqrt(sum((p - sum(pauses)/len(pauses))**2 for p in pauses) / len(pauses))
            pause_mean = sum(pauses) / len(pauses)
            pause_cv = pause_std / pause_mean if pause_mean > 0 else 0

            if pause_cv > 0.3:
                score += 0.5
                details.append(f"Varied pause durations (CV={pause_cv:.2f}) ✓ — human-like")
            else:
                score += 0.1
                details.append(f"Uniform pauses (CV={pause_cv:.2f}) ✗ — looks synthetic")

        self.scores['pause_patterns'] = (score, 1.5, {
            'pause_count': len(pauses),
            'pause_ratio': pause_ratio,
            'details': details,
        })

    def _analyze_backspace_usage(self, press_events: list):
        """
        Humans make typos and correct them with backspace.
        No backspaces at all is a strong signal of automation.
        """
        total = len(press_events)
        backspaces = sum(1 for e in press_events if 'backspace' in e['key'].lower())
        ratio = backspaces / total if total > 0 else 0

        score = 0.0
        details = []

        t = self.THRESHOLDS
        if t['backspace_ratio_human_min'] <= ratio <= t['backspace_ratio_human_max']:
            score = 1.0
            details.append(f"Natural backspace usage ({ratio*100:.1f}%) ✓")
        elif ratio == 0:
            score = 0.0
            details.append(f"Zero backspaces ✗ — strong automation signal")
        elif ratio > t['backspace_ratio_human_max']:
            score = 0.3
            details.append(f"Excessive backspaces ({ratio*100:.1f}%) — unusual")
        else:
            score = 0.4
            details.append(f"Low backspace rate ({ratio*100:.1f}%) — borderline")

        self.scores['backspace_usage'] = (score, 1.0, {
            'backspace_count': backspaces,
            'total_keys': total,
            'ratio': ratio,
            'details': details,
        })

    def _analyze_dwell_times(self):
        """
        Dwell time = duration a key is held down (press to release).
        Humans have variable dwell times. Simulated inputs often have
        near-zero or perfectly uniform dwell times.
        """
        # Match press-release pairs
        pending_presses = {}  # key -> press_timestamp
        dwell_times = []

        for event in self.events:
            key = event['key']
            if event['event'] == 'press':
                pending_presses[key] = event['timestamp']
            elif event['event'] == 'release' and key in pending_presses:
                dwell = event['timestamp'] - pending_presses[key]
                if 0 < dwell < 1.0:  # Sanity check
                    dwell_times.append(dwell)
                del pending_presses[key]

        score = 0.0
        details = []

        if len(dwell_times) >= 5:
            mean_dwell = sum(dwell_times) / len(dwell_times)
            std_dwell = math.sqrt(sum((d - mean_dwell)**2 for d in dwell_times) / len(dwell_times))
            cv_dwell = std_dwell / mean_dwell if mean_dwell > 0 else 0

            r = self.THRESHOLDS['dwell_time_human_range']
            if r[0] <= mean_dwell <= r[1]:
                score += 0.5
                details.append(f"Mean dwell time in human range ({mean_dwell*1000:.1f}ms) ✓")
            elif mean_dwell < 0.01:
                details.append(f"Near-zero dwell times ({mean_dwell*1000:.1f}ms) ✗ — likely simulated")
            else:
                score += 0.2
                details.append(f"Unusual dwell times ({mean_dwell*1000:.1f}ms)")

            if cv_dwell > 0.3:
                score += 0.5
                details.append(f"Variable dwell times (CV={cv_dwell:.2f}) ✓")
            else:
                details.append(f"Uniform dwell times (CV={cv_dwell:.2f}) ✗")
        else:
            score = 0.5
            details.append("Insufficient dwell time data")

        self.scores['dwell_times'] = (score, 1.0, {
            'sample_count': len(dwell_times),
            'details': details,
        })

    def _analyze_burst_uniformity(self, intervals: list):
        """
        Detect segments of rapid typing (bursts) and check if they
        are too metronomically uniform — a strong bot signal.
        """
        burst_threshold = 0.1  # Keys faster than 100ms = burst
        bursts = []
        current_burst = []

        for dt in intervals:
            if dt < burst_threshold:
                current_burst.append(dt)
            else:
                if len(current_burst) >= 3:
                    bursts.append(current_burst)
                current_burst = []
        if len(current_burst) >= 3:
            bursts.append(current_burst)

        score = 0.0
        details = []

        if bursts:
            burst_cvs = []
            for burst in bursts:
                bm = sum(burst) / len(burst)
                bs = math.sqrt(sum((x - bm)**2 for x in burst) / len(burst))
                bcv = bs / bm if bm > 0 else 0
                burst_cvs.append(bcv)

            avg_burst_cv = sum(burst_cvs) / len(burst_cvs)

            if avg_burst_cv > self.THRESHOLDS['burst_uniformity_max']:
                score = 1.0
                details.append(f"Bursts have natural variation (avg CV={avg_burst_cv:.3f}) ✓")
            else:
                score = 0.1
                details.append(f"Bursts are suspiciously uniform (avg CV={avg_burst_cv:.3f}) ✗")

            details.append(f"Detected {len(bursts)} burst segments")
        else:
            score = 0.5
            details.append("No rapid typing bursts detected")

        self.scores['burst_uniformity'] = (score, 1.0, {
            'burst_count': len(bursts),
            'details': details,
        })

    def _analyze_mouse_correlation(self, press_events: list):
        """
        Check if mouse activity correlates with typing activity.
        Humans naturally move the mouse occasionally while typing.
        Pure keyboard automation often has zero mouse activity.
        """
        score = 0.0
        details = []

        if not self.mouse_events:
            score = 0.2
            details.append("No mouse events recorded ✗ — may indicate automation")
        else:
            # Check if mouse events are spread throughout the typing session
            if press_events:
                typing_duration = press_events[-1]['timestamp'] - press_events[0]['timestamp']
                mouse_rate = len(self.mouse_events) / typing_duration if typing_duration > 0 else 0

                if mouse_rate > 0.5:  # Some mouse activity
                    score = 0.8
                    details.append(f"Mouse activity during typing ({mouse_rate:.1f} events/s) ✓")
                elif mouse_rate > 0:
                    score = 0.5
                    details.append(f"Minimal mouse activity ({mouse_rate:.1f} events/s)")
                else:
                    score = 0.2
                    details.append("No mouse movement during typing ✗")

            # Check for mouse micro-jitter patterns (bots sometimes add uniform jitter)
            if len(self.mouse_events) >= 10:
                move_events = [e for e in self.mouse_events if e['event'] == 'move']
                if len(move_events) >= 5:
                    dx_list = []
                    for i in range(1, len(move_events)):
                        dx = abs(move_events[i]['x'] - move_events[i-1]['x'])
                        dy = abs(move_events[i]['y'] - move_events[i-1]['y'])
                        dx_list.append(math.sqrt(dx**2 + dy**2))

                    if dx_list:
                        mean_move = sum(dx_list) / len(dx_list)
                        if mean_move < 5:
                            score *= 0.5  # Suspicious micro-jitter
                            details.append(f"Suspicious micro-jitter pattern (avg {mean_move:.1f}px) ✗")
                        else:
                            details.append(f"Natural mouse movements (avg {mean_move:.1f}px) ✓")

        self.scores['mouse_correlation'] = (score, 0.5, {
            'mouse_event_count': len(self.mouse_events),
            'details': details,
        })

    def _compute_verdict(self) -> dict:
        """Aggregate all feature scores into a final classification."""
        total_weighted_score = 0
        total_weight = 0
        feature_results = {}

        for feature_name, (score, weight, detail) in self.scores.items():
            total_weighted_score += score * weight
            total_weight += weight
            feature_results[feature_name] = {
                'score': round(score, 3),
                'weight': weight,
                'weighted_score': round(score * weight, 3),
                'details': detail.get('details', []),
                'data': {k: v for k, v in detail.items() if k != 'details'},
            }

        overall_score = total_weighted_score / total_weight if total_weight > 0 else 0

        # Classification thresholds
        if overall_score >= 0.7:
            classification = 'HUMAN'
            confidence = min(overall_score, 0.99)
        elif overall_score >= 0.4:
            classification = 'SUSPICIOUS'
            confidence = 1.0 - overall_score  # Lower confidence in the middle
        else:
            classification = 'AUTOMATED'
            confidence = 1.0 - overall_score

        return {
            'classification': classification,
            'overall_score': round(overall_score, 3),
            'confidence': round(confidence, 3),
            'verdict': f"{'🟢' if classification == 'HUMAN' else '🟡' if classification == 'SUSPICIOUS' else '🔴'} {classification}",
            'features': feature_results,
        }


# ──────────────────────────────────────────────
#  Report Printer
# ──────────────────────────────────────────────

def print_report(result: dict):
    """Pretty-print the analysis report."""
    print()
    print("╔══════════════════════════════════════════════════════╗")
    print("║         TYPING BEHAVIOR ANALYSIS REPORT             ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    verdict = result.get('verdict', 'UNKNOWN')
    score = result.get('overall_score', 0)
    confidence = result.get('confidence', 0)

    print(f"  VERDICT:      {verdict}")
    print(f"  HUMAN SCORE:  {score:.1%}")
    print(f"  CONFIDENCE:   {confidence:.1%}")
    print()
    print("─" * 55)

    features = result.get('features', {})
    for name, data in features.items():
        title = name.replace('_', ' ').title()
        s = data['score']
        bar_len = int(s * 20)
        bar = '█' * bar_len + '░' * (20 - bar_len)

        indicator = '✓' if s >= 0.7 else '?' if s >= 0.4 else '✗'
        print(f"\n  [{indicator}] {title}")
        print(f"      Score: [{bar}] {s:.0%}  (weight: {data['weight']}x)")

        for detail in data.get('details', []):
            print(f"      • {detail}")

    print()
    print("─" * 55)

    # Recommendations
    classification = result.get('classification', '')
    if classification == 'HUMAN':
        print("  ✅ Typing behavior is consistent with human input.")
    elif classification == 'SUSPICIOUS':
        print("  ⚠️  Typing behavior has anomalies. Could be automated")
        print("     with some human-like features, or an unusual human typist.")
    elif classification == 'AUTOMATED':
        print("  🚨 Typing behavior is consistent with automated/synthetic input.")
        print("     Key indicators:")
        for name, data in features.items():
            if data['score'] < 0.4:
                for detail in data.get('details', []):
                    if '✗' in detail:
                        print(f"       - {detail}")
    print()


# ──────────────────────────────────────────────
#  Main Entry Point
# ──────────────────────────────────────────────

def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║     Typing Behavior Detector & Verifier v1.0        ║")
    print("║     Educational / Research Use Only                  ║")
    print("╚══════════════════════════════════════════════════════╝")
    print()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python typing_detector.py record    — Record keystrokes to a file")
        print("  python typing_detector.py analyze   — Analyze a recorded session")
        print("  python typing_detector.py monitor   — Record + analyze in one step")
        print()
        sys.exit(0)

    mode = sys.argv[1].lower()
    script_dir = os.path.dirname(os.path.abspath(__file__))

    if mode == 'record':
        duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60
        output_file = os.path.join(script_dir, 'typing_recording.json')

        recorder = KeystrokeRecorder()
        recorder.start_recording(duration_seconds=duration)
        recorder.save_recording(output_file)

    elif mode == 'analyze':
        input_file = sys.argv[2] if len(sys.argv) > 2 else os.path.join(script_dir, 'typing_recording.json')

        if not os.path.exists(input_file):
            print(f"Error: Recording file not found: {input_file}")
            print("Run 'python typing_detector.py record' first.")
            sys.exit(1)

        print(f"Loading recording from: {input_file}")
        data = KeystrokeRecorder.load_recording(input_file)

        analyzer = TypingAnalyzer(
            keyboard_events=data['keyboard_events'],
            mouse_events=data.get('mouse_events', []),
        )
        result = analyzer.analyze()
        print_report(result)

        # Save analysis report
        report_file = os.path.join(script_dir, 'analysis_report.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f"[Saved] Full analysis report: {report_file}")

    elif mode == 'monitor':
        duration = float(sys.argv[2]) if len(sys.argv) > 2 else 60

        # Record
        recorder = KeystrokeRecorder()
        recorder.start_recording(duration_seconds=duration)

        # Save
        output_file = os.path.join(script_dir, 'typing_recording.json')
        recorder.save_recording(output_file)

        # Analyze immediately
        print("\nAnalyzing recorded session...\n")
        analyzer = TypingAnalyzer(
            keyboard_events=recorder.events,
            mouse_events=recorder.mouse_events,
        )
        result = analyzer.analyze()
        print_report(result)

        # Save report
        report_file = os.path.join(script_dir, 'analysis_report.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2)
        print(f"[Saved] Full analysis report: {report_file}")

    else:
        print(f"Unknown mode: {mode}")
        print("Use: record, analyze, or monitor")
        sys.exit(1)


if __name__ == "__main__":
    main()
