"""Challenge-response: random phrases a live person can repeat instantly.

An attacker running a text-to-speech clone must type the phrase and wait for
synthesis, which shows up as response latency (signal B). Phrases are random
word triples so they can't be pre-recorded.
"""
from __future__ import annotations

import secrets

COLOURS = ["blue", "green", "orange", "silver", "purple", "yellow", "red", "golden"]
NOUNS = ["mango", "river", "tiger", "lantern", "pepper", "rocket", "violin", "coconut",
         "monsoon", "falcon", "harbour", "saffron"]
NUMBERS = ["seventeen", "forty two", "ninety one", "sixty eight", "twenty three", "eighty five"]


def challenge_phrase() -> str:
    return f"{secrets.choice(COLOURS)} {secrets.choice(NOUNS)} {secrets.choice(NUMBERS)}"


# ------------------------------------------------------------------ verification
NUM_DIGITS = {"seventeen": "17", "forty two": "42", "ninety one": "91", "sixty eight": "68",
              "twenty three": "23", "eighty five": "85"}
MATCH_OK = 0.66  # at least 2 of the 3 phrase parts must be heard (2/3 = 0.667)


def _tokens(text: str) -> list[str]:
    t = text.lower()
    for words, digits in NUM_DIGITS.items():
        t = t.replace(words, digits).replace(words.replace(" ", "-"), digits)
    return "".join(ch if ch.isalnum() else " " for ch in t).split()


def phrase_match(phrase: str, heard: str) -> float:
    """Fraction of the challenge's parts (colour, noun, number) present in what was heard."""
    want = _tokens(phrase)
    parts = [want[0], want[1], want[-1]] if len(want) >= 3 else want
    got = set(_tokens(heard))
    return sum(p in got for p in parts) / len(parts) if parts else 0.0
