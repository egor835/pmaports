#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
t9d - multi-tap text entry for phone keypads.

Grabs the keypad input device and re-emits its keys through a uinput
keyboard, turning the digit keys into letters the way feature phones do:

  2..9       letters, press repeatedly to cycle (a -> b -> c -> 2 ...)
  1          punctuation
  0          space (then 0)
  hold digit the digit itself
  #          next mode: abc -> Abc -> ABC -> 123
  hold #     t9d off / on (all keys pass through untouched)
  *          symbols, press repeatedly to cycle

Everything else (arrows, enter, back, call, ...) passes through unchanged.
"""

import argparse
import select
import sys
import time

import evdev
from evdev import UInput, ecodes as e

MULTITAP = {
    e.KEY_1: ".,?!'\"-@:;/()1",
    e.KEY_2: "abc2",
    e.KEY_3: "def3",
    e.KEY_4: "ghi4",
    e.KEY_5: "jkl5",
    e.KEY_6: "mno6",
    e.KEY_7: "pqrs7",
    e.KEY_8: "tuv8",
    e.KEY_9: "wxyz9",
    e.KEY_0: " 0",
    e.KEY_NUMERIC_STAR: "*+-=#%&<>[]{}_~^|\\$",
}
DIGIT = {
    e.KEY_1: "1", e.KEY_2: "2", e.KEY_3: "3", e.KEY_4: "4", e.KEY_5: "5",
    e.KEY_6: "6", e.KEY_7: "7", e.KEY_8: "8", e.KEY_9: "9", e.KEY_0: "0",
    e.KEY_NUMERIC_STAR: "*",
}
MODES = ["abc", "Abc", "ABC", "123"]

# character -> (keycode, shift) for a US layout
CHARMAP = {" ": (e.KEY_SPACE, False)}
for c in "abcdefghijklmnopqrstuvwxyz":
    code = getattr(e, "KEY_" + c.upper())
    CHARMAP[c] = (code, False)
    CHARMAP[c.upper()] = (code, True)
for c, name in zip("1234567890", "1234567890"):
    CHARMAP[c] = (getattr(e, "KEY_" + name), False)
for c, code, shift in [
    (".", e.KEY_DOT, False), (",", e.KEY_COMMA, False), ("?", e.KEY_SLASH, True),
    ("!", e.KEY_1, True), ("'", e.KEY_APOSTROPHE, False), ('"', e.KEY_APOSTROPHE, True),
    ("-", e.KEY_MINUS, False), ("@", e.KEY_2, True), (":", e.KEY_SEMICOLON, True),
    (";", e.KEY_SEMICOLON, False), ("/", e.KEY_SLASH, False), ("(", e.KEY_9, True),
    (")", e.KEY_0, True), ("*", e.KEY_8, True), ("+", e.KEY_EQUAL, True),
    ("=", e.KEY_EQUAL, False), ("#", e.KEY_3, True), ("%", e.KEY_5, True),
    ("&", e.KEY_7, True), ("<", e.KEY_COMMA, True), (">", e.KEY_DOT, True),
    ("[", e.KEY_LEFTBRACE, False), ("]", e.KEY_RIGHTBRACE, False),
    ("{", e.KEY_LEFTBRACE, True), ("}", e.KEY_RIGHTBRACE, True),
    ("_", e.KEY_MINUS, True), ("~", e.KEY_GRAVE, True), ("^", e.KEY_6, True),
    ("|", e.KEY_BACKSLASH, True), ("\\", e.KEY_BACKSLASH, False), ("$", e.KEY_4, True),
]:
    CHARMAP[c] = (code, shift)


class T9:
    def __init__(self, dev, timeout, hold):
        self.dev = dev
        self.timeout = timeout
        self.hold = hold
        self.mode = 0
        self.enabled = True
        # pending multi-tap: key, index into its letters, time of last tap
        self.tap_key = None
        self.tap_idx = 0
        self.tap_time = 0.0
        self.capital_next = False
        # key held down: key, press time, whether the hold action fired
        self.down = {}

        keys = set(dev.capabilities().get(e.EV_KEY, []))
        keys |= {code for code, _ in CHARMAP.values()}
        keys |= {e.KEY_LEFTSHIFT, e.KEY_BACKSPACE, e.KEY_SPACE}
        self.ui = UInput({e.EV_KEY: sorted(keys)}, name="t9d keyboard")

    # output helpers
    def key(self, code, value):
        self.ui.write(e.EV_KEY, code, value)
        self.ui.syn()

    def tap(self, code, shift=False):
        if shift:
            self.key(e.KEY_LEFTSHIFT, 1)
        self.key(code, 1)
        self.key(code, 0)
        if shift:
            self.key(e.KEY_LEFTSHIFT, 0)

    def type_char(self, ch):
        code, shift = CHARMAP[ch]
        self.tap(code, shift)

    def letter_case(self, ch):
        mode = MODES[self.mode]
        if mode == "ABC":
            return ch.upper()
        if mode == "Abc" and self.capital_next:
            return ch.upper()
        return ch

    def commit(self):
        """Finish the pending multi-tap character."""
        if self.tap_key is None:
            return
        ch = MULTITAP[self.tap_key][self.tap_idx]
        if MODES[self.mode] == "Abc" and ch.isalpha():
            self.capital_next = False
        if MODES[self.mode] == "Abc" and ch in ".?!":
            self.capital_next = True
        self.tap_key = None

    def show(self, msg):
        print(msg, flush=True)

    # input handling
    def press(self, code):
        now = time.monotonic()

        if code == e.KEY_NUMERIC_POUND:
            self.down[code] = [now, False]
            return

        if not self.enabled or code not in MULTITAP or MODES[self.mode] == "123":
            if code in DIGIT and self.enabled:
                self.commit()
                self.type_char(DIGIT[code])
            else:
                self.commit()
                self.key(code, 1)
            return

        self.down[code] = [now, False]

        letters = MULTITAP[code]
        if code == self.tap_key and now - self.tap_time < self.timeout:
            # next letter on the same key: replace the previous one
            self.tap_idx = (self.tap_idx + 1) % len(letters)
            self.tap(e.KEY_BACKSPACE)
        else:
            self.commit()
            self.tap_key = code
            self.tap_idx = 0
        self.tap_time = now
        self.type_char(self.letter_case(letters[self.tap_idx]))

    def release(self, code):
        held = self.down.pop(code, None)

        if code == e.KEY_NUMERIC_POUND:
            if held and not held[1]:
                if not self.enabled:
                    self.tap(e.KEY_3, True)
                else:
                    self.commit()
                    self.mode = (self.mode + 1) % len(MODES)
                    self.capital_next = MODES[self.mode] == "Abc"
                    self.show("mode " + MODES[self.mode])
            return

        if held is None:
            if not (code in DIGIT and self.enabled):
                self.key(code, 0)

    def poll_holds(self):
        now = time.monotonic()
        for code, held in self.down.items():
            if held[1] or now - held[0] < self.hold:
                continue
            held[1] = True
            if code == e.KEY_NUMERIC_POUND:
                self.commit()
                self.enabled = not self.enabled
                self.show("t9d " + ("on" if self.enabled else "off"))
            elif code in DIGIT:
                # replace the letter typed on press with the digit
                self.tap(e.KEY_BACKSPACE)
                self.tap_key = None
                self.type_char(DIGIT[code])
        if self.tap_key is not None and now - self.tap_time >= self.timeout:
            self.commit()

    def run(self):
        self.dev.grab()
        try:
            while True:
                r, _, _ = select.select([self.dev.fd], [], [], 0.05)
                if r:
                    for ev in self.dev.read():
                        if ev.type != e.EV_KEY:
                            continue
                        if ev.value == 1:
                            self.press(ev.code)
                        elif ev.value == 0:
                            self.release(ev.code)
                self.poll_holds()
        finally:
            self.dev.ungrab()


def find_device(name):
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        if dev.name == name:
            return dev
        dev.close()
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--device", default="pp2106-keypad", help="input device name")
    ap.add_argument("--timeout", type=float, default=0.8, help="multi-tap timeout, s")
    ap.add_argument("--hold", type=float, default=0.6, help="long-press time, s")
    args = ap.parse_args()

    dev = None
    for _ in range(60):
        dev = find_device(args.device)
        if dev:
            break
        time.sleep(1)
    if not dev:
        sys.exit(f"input device '{args.device}' not found")

    T9(dev, args.timeout, args.hold).run()


if __name__ == "__main__":
    main()
