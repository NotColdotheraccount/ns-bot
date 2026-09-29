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
    WHY_MISS = auto()      # "why do you miss me"
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
    "i miss", "wish you were here", "want you here",
    "come home", "come back",
)

_WHY_WORDS = ("why", "whyy", "y", "hw", "how come")

_MISS_WORDS = ("miss", "missing", "missed")

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

    # Checked before MISSING: "why do you miss me" contains a missing phrase,
    # so the more specific question has to win or it never fires.
    if _is_why_miss(normalised):
        return Intent.WHY_MISS

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

def _is_why_miss(normalised: str) -> bool:
    """True for 'why do you miss me' and its many spellings.

    Matching on structure rather than a list of exact phrases, because there
    are too many ways to type it: why / whyy / y, do you / u / you, miss me /
    missing me. The rule is simply: it opens with a why-word and mentions
    missing. Anything longer than a short question is ignored, so "i was
    wondering why you miss me so much when..." stays a plain missing message.
    """
    words = normalised.split()
    if not words or len(words) > 8:
        return False

    opens_with_why = words[0] in _WHY_WORDS or normalised.startswith("how come")
    if not opens_with_why:
        return False

    return any(word in _MISS_WORDS for word in words)

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
