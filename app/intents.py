"""Deterministic intent detection.

Your spec was explicit that "another memory" must not cost a Claude call, and
this module is how that promise is kept. Every feature that can be served by
keyword matching is served by keyword matching: no API latency, no token spend,
no failure mode when the network is down, and identical behaviour every time.

Claude is reserved for the AI Chat topic and for Ask Past Me fallback, where
open-ended language genuinely is the point.

Deliberately simple. Matching is substring-based on a normalised string, which
handles the realistic input ("another one", "ANOTHER", "another one pls 🥺")
without pretending to be a parser.
"""

from __future__ import annotations

import re
from enum import StrEnum, auto

# Strip punctuation and emoji so "another one!!! 🥺" matches "another one".
_NOISE = re.compile(r"[^\w\s]", flags=re.UNICODE)


def normalise(text: str) -> str:
    """Lowercase, strip punctuation, and collapse whitespace."""
    cleaned = _NOISE.sub(" ", text.lower())
    return " ".join(cleaned.split())


def contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    """True if the normalised text contains any of the given phrases."""
    normalised = normalise(text)
    return any(phrase in normalised for phrase in phrases)


class Intent(StrEnum):
    """What she is asking for, inferred from phrasing."""

    ANOTHER = auto()       # "another", "again", "one more"
    MISSING = auto()       # "i miss you"
    SAD = auto()           # "i had a bad day", "im sad"
    SPECIFIC_MOOD = auto() # "something sad", "something cute"
    GENERIC = auto()       # anything else — still a valid request


_ANOTHER = (
    "another", "again", "one more", "more", "next", "keep going",
    "encore", "lagi",
)

_MISSING = (
    "miss you", "miss u", "miss him", "missing you", "missing u",
    "i miss", "rindu", "wish you were here", "want you here",
    "come home", "come back",
)

_SAD = (
    "bad day", "rough day", "awful day", "terrible day", "hard day",
    "im sad", "i m sad", "feeling sad", "so tired", "exhausted",
    "stressed", "overwhelmed", "crying", "cried", "upset", "down",
)

# Mood words that can be pulled straight out of a request and used as a tag.
_MOOD_WORDS = (
    "sad", "happy", "cute", "funny", "soft", "sleepy", "calm",
    "romantic", "silly", "comfort", "motivation",
)


def detect_intent(text: str) -> Intent:
    """Classify a message. Order matters — most specific first."""
    if not text or not text.strip():
        return Intent.GENERIC

    normalised = normalise(text)

    # Checked before ANOTHER so "i miss you, send another" reads as missing.
    if any(phrase in normalised for phrase in _MISSING):
        return Intent.MISSING
    if any(phrase in normalised for phrase in _SAD):
        return Intent.SAD
    if extract_mood(text) is not None:
        return Intent.SPECIFIC_MOOD
    if any(phrase in normalised for phrase in _ANOTHER):
        return Intent.ANOTHER
    return Intent.GENERIC


def extract_mood(text: str) -> str | None:
    """Pull a mood tag out of a request like 'something sad'.

    Requires a leading word ('something sad', 'a cute one') so that a message
    that merely mentions being sad is not mistaken for a request for sad
    content — that distinction matters in the Bad Day flow.
    """
    normalised = normalise(text)
    for mood in _MOOD_WORDS:
        for prefix in ("something ", "anything ", "a ", "an ", "play ", "send "):
            if f"{prefix}{mood}" in normalised:
                return mood
    return None
