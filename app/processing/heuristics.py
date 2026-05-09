"""
Heuristic Algorithm Selector for APME.

All decisions are purely rule-based — no ML.  The selector analyses:
  - Number of patterns          → single vs. multi-pattern path
  - Pattern length (in bytes)   → affects which single-pass algorithm fits
  - Script type                 → does the pattern contain non-ASCII (Hebrew etc.)?
  - Text entropy / monotonicity → how varied is the character distribution?
  - Text length                 → very large texts may prefer sub-linear BM

Selection table (from project proposal):
┌─────────────────────────────────────────┬──────────────────┐
│ Condition                               │ Algorithm        │
├─────────────────────────────────────────┼──────────────────┤
│ num_patterns > 1                        │ Aho-Corasick     │
│ pattern_len ≤ 64 bytes AND ascii-only   │ Shift-Or         │
│ pattern_len ≤ 4 bytes                   │ KMP              │
│ text is monotone (entropy < threshold)  │ KMP              │
│ pattern contains non-ASCII (e.g. Hebrew)│ KMP              │
│ text_len > LARGE_FILE / natural text    │ Boyer-Moore      │
│ default                                 │ Boyer-Moore      │
└─────────────────────────────────────────┴──────────────────┘
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

# Thresholds (all sizes in bytes)
_SHORT_PATTERN  = 4        # KMP beats BM for very short patterns
_BITAP_MAX      = 64       # Shift-Or supports patterns up to 64 bytes
_LARGE_TEXT     = 5 * 1024 * 1024   # 5 MB — parallel chunking kicks in
_HUGE_TEXT      = 50 * 1024 * 1024  # 50 MB — streaming instead of RAM load
_ENTROPY_MONO   = 2.0      # bits; below this the text is "monotone"


# ── Text profiling ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TextProfile:
    length:        int
    unique_bytes:  int
    entropy:       float   # Shannon entropy in bits
    is_monotone:   bool    # very low entropy / few distinct chars
    is_natural:    bool    # looks like natural language (high entropy, many chars)
    has_non_ascii: bool    # contains bytes >= 0x80 (Hebrew, Arabic, CJK …)
    top_byte_freq: float   # fraction of text occupied by the most common byte


def profile_text(data: bytes) -> TextProfile:
    n = len(data)
    if n == 0:
        return TextProfile(0, 0, 0.0, True, False, False, 0.0)

    freq = [0] * 256
    for b in data:
        freq[b] += 1

    unique    = sum(1 for f in freq if f)
    top_freq  = max(freq) / n
    has_non_ascii = any(freq[i] for i in range(128, 256))

    # Shannon entropy
    entropy = 0.0
    for f in freq:
        if f:
            p = f / n
            entropy -= p * math.log2(p)

    is_monotone = entropy < _ENTROPY_MONO or unique < 20
    is_natural  = entropy > 4.5 and unique > 60

    return TextProfile(
        length=n,
        unique_bytes=unique,
        entropy=entropy,
        is_monotone=is_monotone,
        is_natural=is_natural,
        has_non_ascii=has_non_ascii,
        top_byte_freq=top_freq,
    )


def profile_pattern(pattern: bytes) -> dict:
    has_non_ascii = any(b >= 0x80 for b in pattern)
    return {
        "length":        len(pattern),
        "has_non_ascii": has_non_ascii,
        "is_ascii_only": not has_non_ascii,
    }


# ── Core selection logic ──────────────────────────────────────────────────────

ALGORITHMS = frozenset({"KMP", "Boyer-Moore", "Rabin-Karp", "Shift-Or",
                         "Aho-Corasick", "Fuzzy"})


def select_algorithm(
    pattern:      bytes | Sequence[bytes],
    text_sample:  bytes | None = None,
    text_len:     int = 0,
    *,
    multi_pattern: bool = False,
) -> str:
    """
    Return the name of the best algorithm for the given inputs.

    Parameters
    ----------
    pattern      : single pattern bytes, or list of pattern bytes
    text_sample  : a representative sample of the text (up to first 64 KB)
    text_len     : total length of the text in bytes
    multi_pattern: True when caller wants to search for several patterns at once
    """
    # ── 1. Multi-pattern path ────────────────────────────────────────────────
    if multi_pattern or (isinstance(pattern, (list, tuple)) and len(pattern) > 1):
        return "Aho-Corasick"

    # Normalise to single pattern
    pat: bytes = pattern[0] if isinstance(pattern, (list, tuple)) else pattern  # type: ignore
    m = len(pat)

    if m == 0:
        return "KMP"   # degenerate; KMP handles gracefully

    pat_info = profile_pattern(pat)

    # ── 2. Profile available text sample ────────────────────────────────────
    if text_sample:
        tp = profile_text(text_sample)
    else:
        tp = TextProfile(
            length=text_len, unique_bytes=128, entropy=5.0,
            is_monotone=False, is_natural=True,
            has_non_ascii=pat_info["has_non_ascii"], top_byte_freq=0.05,
        )

    effective_len = text_len or tp.length

    # ── 3. Decision tree ─────────────────────────────────────────────────────

    # Non-ASCII pattern (Hebrew, Arabic, CJK…):
    #   BM's skip tables are less effective because multi-byte sequences share
    #   0x80-0xBF continuation bytes, reducing useful skip distances.
    if pat_info["has_non_ascii"]:
        return "KMP"

    # Very short pattern: KMP's failure-table overhead dominates, BM good-suffix
    # gain is tiny.  KMP is simpler and equally fast.
    if m <= _SHORT_PATTERN:
        return "KMP"

    # Bit-parallel Shift-Or: optimal for short ASCII patterns (≤64 bytes)
    # where bit-parallelism gives constant-time character comparisons.
    if m <= _BITAP_MAX and pat_info["is_ascii_only"]:
        if tp.is_monotone:
            # Monotone text: BM can't skip; KMP linear scan is better.
            return "KMP"
        return "Shift-Or"

    # Monotone / highly repetitive text: BM skip tables degrade; KMP guaranteed.
    if tp.is_monotone:
        return "KMP"

    # Large natural-language text with a medium-to-long ASCII pattern:
    # Boyer-Moore achieves sub-linear average complexity.
    if tp.is_natural or effective_len > _LARGE_TEXT:
        return "Boyer-Moore"

    # Default
    return "Boyer-Moore"


def explain_selection(
    algorithm: str,
    pattern: bytes,
    text_sample: bytes | None,
    text_len: int,
) -> str:
    """Return a human-readable explanation of the algorithm choice."""
    m   = len(pattern)
    tp  = profile_text(text_sample) if text_sample else None
    reasons = []

    if algorithm == "Aho-Corasick":
        reasons.append("multiple patterns → Aho-Corasick simultaneous search")
    elif algorithm == "KMP":
        if any(b >= 0x80 for b in pattern):
            reasons.append("non-ASCII pattern (Hebrew/Unicode) → KMP byte-level scan")
        elif m <= 4:
            reasons.append(f"very short pattern ({m}B) → KMP avoids BM table overhead")
        elif tp and tp.is_monotone:
            reasons.append(f"monotone text (entropy={tp.entropy:.2f}b) → KMP guaranteed O(n+m)")
        else:
            reasons.append("KMP: safe linear-time guarantee")
    elif algorithm == "Shift-Or":
        reasons.append(f"ASCII pattern ≤64B ({m}B) → bit-parallel Shift-Or")
    elif algorithm == "Boyer-Moore":
        reasons.append(f"natural/varied text, long pattern ({m}B) → BM sub-linear skips")
    elif algorithm == "Rabin-Karp":
        reasons.append("rolling-hash path selected")
    elif algorithm == "Fuzzy":
        reasons.append("approximate matching requested")

    if tp:
        reasons.append(
            f"text profile: len={text_len}B entropy={tp.entropy:.2f}b "
            f"unique_bytes={tp.unique_bytes} non_ascii={tp.has_non_ascii}"
        )

    return "; ".join(reasons)
