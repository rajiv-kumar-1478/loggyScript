"""
Human-Like Typing Simulator
============================
Simulates realistic human typing behavior including:
  - Variable inter-key delays based on digraph difficulty
  - Occasional typos with backspace corrections
  - Thinking pauses at logical breakpoints (newlines, after punctuation)
  - Burst typing for common programming tokens
  - Mouse micro-jitter to simulate natural hand movement
  - Fatigue modeling (typing slows down over time)

Usage:
  1. pip install pynput
  2. python human_typer.py
  3. Click into VS Code (or any editor) within the countdown window
  4. The script types the sample code with human-like behavior

WARNING: This is for educational / research purposes only.
"""

import time
import random
import math
import threading

try:
    from pynput.keyboard import Controller as KeyboardController, Key
    from pynput.mouse import Controller as MouseController
except ImportError:
    print("ERROR: pynput is required. Install it with:")
    print("  pip install pynput")
    exit(1)


# ──────────────────────────────────────────────
#  Configuration
# ──────────────────────────────────────────────

class TypingProfile:
    """Configurable profile that controls how 'human' the typing looks."""

    def __init__(self):
        # Base inter-key delay range (seconds)
        self.base_delay_min = 0.04       # Fast typist floor
        self.base_delay_max = 0.14       # Normal ceiling

        # Typo settings
        self.typo_probability = 0.04     # 4% chance per character
        self.typo_correction_delay = (0.15, 0.45)  # Pause before fixing typo

        # Thinking and cognitive pauses (all randomized ranges)
        self.pause_after_word = (0.05, 0.20)         # Natural pause after typing each word
        self.pause_word_thinking_prob = 0.15         # Chance of slightly longer word pause
        self.pause_word_thinking = (0.18, 0.45)
        self.pause_after_newline = (0.3, 1.8)        # Pause after pressing Enter
        self.pause_after_period = (0.2, 0.8)         # Pause after sentence end
        self.pause_thinking_probability = 0.02       # Random "thinking" pause
        self.pause_thinking_duration = (0.8, 3.0)    # How long a thinking pause lasts

        # Burst typing for common tokens
        self.burst_tokens = [
            "def ", "return ", "import ", "from ", "class ",
            "self.", "print(", "if ", "else:", "elif ",
            "for ", "while ", "try:", "except ", "with ",
            "True", "False", "None", "async ", "await ",
            "    ",  # Tab indentation as spaces
        ]
        self.burst_speed_multiplier = 0.5  # Type bursts faster

        # Fatigue model
        self.fatigue_onset_chars = 200       # After N chars, fatigue kicks in
        self.fatigue_slowdown_factor = 0.02  # Extra delay per 100 chars beyond onset

        # Mouse micro-jitter
        self.mouse_jitter_probability = 0.03   # Chance of mouse micro-movement per keystroke
        self.mouse_jitter_range = (-3, 3)       # Pixel range for jitter

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

        # Digraph difficulty map — awkward finger transitions are slower
        self.slow_digraphs = {
            'zx', 'xz', 'qp', 'pq', 'zq', 'qz',
            'bf', 'fb', 'gn', 'ng', 'mj', 'jm',
            'aq', 'qa', 'pl', 'lp',
        }
        self.fast_digraphs = {
            'th', 'he', 'in', 'er', 'an', 'en', 'on', 'at',
            'es', 'ed', 'te', 'ti', 'or', 'st', 'ar', 'nd',
            'to', 'nt', 'is', 'of', 'it', 'al', 'as', 'ha',
            'et', 'se', 'ou', 're', 'ne', 'ea', 'ri', 'ni',
            'de', 'el', 'le', 'sa', 'si', 'ta',
        }


# ──────────────────────────────────────────────
#  Core Typing Engine
# ──────────────────────────────────────────────

class HumanTyper:
    """Simulates human-like typing with realistic imperfections."""

    def __init__(self, profile: TypingProfile = None):
        self.profile = profile or TypingProfile()
        self.keyboard = KeyboardController()
        self.mouse = MouseController()
        self.chars_typed = 0
        self._stop_event = threading.Event()

    def stop(self):
        """Signal the typer to stop."""
        self._stop_event.set()

    def _get_inter_key_delay(self, prev_char: str, curr_char: str) -> float:
        """
        Calculate delay between two keystrokes based on:
        - Base random delay
        - Digraph difficulty (fast common pairs, slow awkward reaches)
        - Fatigue accumulation
        """
        p = self.profile

        # Base delay with slight right-skew (log-normal feels more natural)
        base = random.lognormvariate(
            math.log((p.base_delay_min + p.base_delay_max) / 2),
            random.uniform(0.30, 0.40)
        )
        base = max(p.base_delay_min * random.uniform(0.85, 1.05),
                   min(base, p.base_delay_max * random.uniform(1.8, 2.2)))

        # Digraph adjustments with randomized variance
        digraph = (prev_char + curr_char).lower()
        if digraph in p.fast_digraphs:
            base *= random.uniform(0.55, 0.70)
        elif digraph in p.slow_digraphs:
            base *= random.uniform(1.35, 1.65)

        # Shift key overhead — uppercase or symbols require holding shift
        if curr_char.isupper() or curr_char in '!@#$%^&*()_+{}|:"<>?~':
            base += random.uniform(0.02, 0.065)

        # Fatigue model
        if self.chars_typed > p.fatigue_onset_chars:
            fatigue = (self.chars_typed - p.fatigue_onset_chars) / 100.0
            base += fatigue * p.fatigue_slowdown_factor * random.uniform(0.8, 1.2)

        # Add Gaussian micro-jitter to prevent any fixed timing
        jitter = random.gauss(0, 0.006)
        base = max(0.015, base + jitter)

        return base

    def _generate_typo(self, char: str) -> str:
        """Generate a realistic typo by hitting a neighboring key."""
        neighbors = self.profile.key_neighbors.get(char.lower(), '')
        if neighbors:
            typo = random.choice(neighbors)
            return typo.upper() if char.isupper() else typo
        return char  # No neighbor data — skip typo

    def _mouse_jitter(self):
        """Simulate subtle mouse micro-movements (hand resting on mouse)."""
        r = self.profile.mouse_jitter_range
        dx = random.randint(r[0], r[1])
        dy = random.randint(r[0], r[1])
        try:
            self.mouse.move(dx, dy)  # relative move from the current position
            time.sleep(random.uniform(0.01, 0.05))
        except Exception:
            pass  # Mouse control may fail in some environments

    def _type_char(self, char: str):
        """Type a single character using pynput."""
        if char == '\n':
            self.keyboard.press(Key.enter)
            self.keyboard.release(Key.enter)
        elif char == '\t':
            self.keyboard.press(Key.tab)
            self.keyboard.release(Key.tab)
        else:
            self.keyboard.type(char)

    def _backspace(self):
        """Press backspace once."""
        self.keyboard.press(Key.backspace)
        self.keyboard.release(Key.backspace)

    def _check_burst_token(self, text: str, position: int) -> str:
        """Check if the current position starts a burst-typeable token."""
        remaining = text[position:]
        for token in sorted(self.profile.burst_tokens, key=len, reverse=True):
            if remaining.startswith(token):
                return token
        return None

    def type_text(self, text: str, initial_delay: float = 5.0):
        """
        Type the given text with human-like behavior.

        Args:
            text: The text to type
            initial_delay: Seconds to wait before starting (to switch windows)
        """
        print(f"\n{'='*50}")
        print(f"  HUMAN TYPER — Starting in {initial_delay:.0f} seconds")
        print(f"  Switch to your target window NOW!")
        print(f"  Press Ctrl+C to abort at any time")
        print(f"{'='*50}\n")

        # Countdown
        for i in range(int(initial_delay), 0, -1):
            if self._stop_event.is_set():
                return
            print(f"  Starting in {i}...", end='\r')
            time.sleep(1)
        print(f"  {'Typing started!':<30}")

        p = self.profile
        prev_char = ''
        i = 0

        while i < len(text):
            if self._stop_event.is_set():
                print("\n[Stopped by user]")
                return

            char = text[i]

            # ── Check for burst token ──
            burst = self._check_burst_token(text, i)
            if burst and random.random() < 0.7:  # 70% chance to burst-type
                for bc in burst:
                    if self._stop_event.is_set():
                        return
                    burst_mult = p.burst_speed_multiplier * random.uniform(0.85, 1.15)
                    delay = self._get_inter_key_delay(prev_char, bc) * burst_mult
                    time.sleep(delay)
                    self._type_char(bc)
                    prev_char = bc
                    self.chars_typed += 1
                i += len(burst)
                # Word-level pause after finishing burst token
                time.sleep(random.uniform(*p.pause_after_word))
                continue

            # ── Thinking pause (random) ──
            if random.random() < p.pause_thinking_probability:
                pause = random.uniform(*p.pause_thinking_duration)
                time.sleep(pause)

            # ── Mouse jitter ──
            if random.random() < p.mouse_jitter_probability:
                self._mouse_jitter()

            # ── Typo injection ──
            if (char.isalpha() and
                    random.random() < p.typo_probability and
                    i > 5):  # Don't typo the very first few chars
                typo_char = self._generate_typo(char)
                self._type_char(typo_char)
                self.chars_typed += 1

                # Brief pause — "noticing" the mistake
                time.sleep(random.uniform(*p.typo_correction_delay))

                # Backspace to fix it
                self._backspace()
                time.sleep(random.uniform(0.05, 0.15))

                # Now type the correct character
                self._type_char(char)
                self.chars_typed += 1
            else:
                # ── Normal keystroke ──
                delay = self._get_inter_key_delay(prev_char, char)
                time.sleep(delay)
                self._type_char(char)
                self.chars_typed += 1

            # ── Post-character pauses (with natural randomness) ──
            if char == '\n':
                time.sleep(random.uniform(*p.pause_after_newline))
            elif char in '.;:':
                time.sleep(random.uniform(*p.pause_after_period))
            elif char in '{}':
                time.sleep(random.uniform(0.1, 0.5))
            elif char == ' ':
                # Word boundary pause - every word type has random inter-word delay
                if random.random() < p.pause_word_thinking_prob:
                    time.sleep(random.uniform(*p.pause_word_thinking))
                else:
                    time.sleep(random.uniform(*p.pause_after_word))
            elif prev_char.isalnum() and not char.isalnum() and char not in ' \t\r\n':
                if random.random() < 0.35:
                    time.sleep(random.uniform(0.04, 0.12))

            prev_char = char
            i += 1

        print(f"\n\n[Done] Typed {self.chars_typed} characters total.")


# ──────────────────────────────────────────────
#  Sample Code to Type
# ──────────────────────────────────────────────

SAMPLE_CODE = '''def fibonacci(n):
    """Return the nth Fibonacci number."""
    if n <= 0:
        return 0
    elif n == 1:
        return 1

    prev, curr = 0, 1
    for i in range(2, n + 1):
        prev, curr = curr, prev + curr
    return curr


def main():
    print("Fibonacci Sequence Generator")
    count = int(input("How many numbers? "))

    for i in range(count):
        result = fibonacci(i)
        print(f"F({i}) = {result}")


if __name__ == "__main__":
    main()
'''


# ──────────────────────────────────────────────
#  Entry Point
# ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("╔══════════════════════════════════════════════╗")
    print("║     Human-Like Typing Simulator v1.0        ║")
    print("║     Educational / Research Use Only          ║")
    print("╚══════════════════════════════════════════════╝")
    print()

    # Allow custom text via command line argument (file path)
    if len(sys.argv) > 1:
        filepath = sys.argv[1]
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                text = f.read()
            print(f"Loaded text from: {filepath}")
        except FileNotFoundError:
            print(f"File not found: {filepath}")
            sys.exit(1)
    else:
        text = SAMPLE_CODE
        print("Using built-in sample code (Fibonacci).")
        print("Tip: Pass a file path as argument to type custom text.")

    print(f"Text length: {len(text)} characters\n")

    profile = TypingProfile()

    # ── Optional: Tweak profile for testing ──
    # profile.typo_probability = 0.06        # More typos
    # profile.base_delay_max = 0.18          # Slower typing
    # profile.fatigue_onset_chars = 100      # Fatigue kicks in earlier

    typer = HumanTyper(profile)

    try:
        typer.type_text(text, initial_delay=5)
    except KeyboardInterrupt:
        typer.stop()
        print("\n\n[Aborted by user]")
