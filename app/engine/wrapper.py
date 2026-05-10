"""
High-level Python wrapper over the APME C engine.

All public functions accept str or bytes for text/pattern and always return:
    SearchResult(matches: list[int], duration_ms: float, algorithm: str)

Indices are byte offsets into the UTF-8 encoded text.
"""

from __future__ import annotations

import ctypes
from dataclasses import dataclass, field
from typing import Sequence

from app.engine.loader import get_lib

# Maximum number of matches pre-allocated per call.
# Increase if you expect more matches in a single search.
MAX_RESULTS = 200_000


@dataclass
class SearchResult:
    matches:     list[int]       # byte offsets of match starts (or ends for fuzzy)
    duration_ms: float
    algorithm:   str
    total_count: int             # actual total (may exceed len(matches) if truncated)
    truncated:   bool = field(init=False)

    def __post_init__(self):
        self.truncated = self.total_count > len(self.matches)


# ── helpers ───────────────────────────────────────────────────────────────────

def _encode(s: str | bytes) -> bytes:
    if isinstance(s, str):
        return s.encode("utf-8")
    return s


def _make_buf(n: int) -> ctypes.Array:
    return (ctypes.c_int * n)()


_ALG_LABELS: dict[str, str] = {
    "apme_kmp":          "KMP",
    "apme_boyer_moore":  "Boyer-Moore",
    "apme_rabin_karp":   "Rabin-Karp",
    "apme_shift_or":     "Shift-Or",
}


def _call_single(fn_name: str, text_b: bytes, pat_b: bytes) -> SearchResult:
    lib = get_lib()
    fn  = getattr(lib, fn_name)

    t_len   = len(text_b)
    p_len   = len(pat_b)
    buf     = _make_buf(MAX_RESULTS)
    dur     = ctypes.c_double(0.0)

    count = fn(text_b, t_len, pat_b, p_len, buf, MAX_RESULTS, ctypes.byref(dur))

    if count < 0:
        raise MemoryError(f"{fn_name}: C allocation failed")

    filled  = min(count, MAX_RESULTS)
    matches = list(buf[:filled])
    label   = _ALG_LABELS.get(fn_name, fn_name.replace("apme_", "").upper())
    return SearchResult(matches, dur.value, label, count)


# ── Public API ────────────────────────────────────────────────────────────────

def search_kmp(text: str | bytes, pattern: str | bytes) -> SearchResult:
    return _call_single("apme_kmp", _encode(text), _encode(pattern))


def search_boyer_moore(text: str | bytes, pattern: str | bytes) -> SearchResult:
    return _call_single("apme_boyer_moore", _encode(text), _encode(pattern))


def search_rabin_karp(text: str | bytes, pattern: str | bytes) -> SearchResult:
    return _call_single("apme_rabin_karp", _encode(text), _encode(pattern))


def search_shift_or(text: str | bytes, pattern: str | bytes) -> SearchResult:
    return _call_single("apme_shift_or", _encode(text), _encode(pattern))


def search_aho_corasick(
    text: str | bytes,
    patterns: Sequence[str | bytes],
) -> dict[str, SearchResult]:
    """
    Multi-pattern search.  Returns a dict keyed by pattern (decoded as UTF-8).
    """
    lib = get_lib()

    text_b   = _encode(text)
    pats_b   = [_encode(p) for p in patterns]
    n_pats   = len(pats_b)
    t_len    = len(text_b)

    # Build C arrays
    c_pat_arr  = (ctypes.c_char_p * n_pats)(*pats_b)
    c_pat_lens = (ctypes.c_int    * n_pats)(*[len(p) for p in pats_b])
    res_buf    = _make_buf(MAX_RESULTS)
    pid_buf    = _make_buf(MAX_RESULTS)
    dur        = ctypes.c_double(0.0)

    count = lib.apme_aho_corasick(
        text_b, t_len,
        c_pat_arr, c_pat_lens, n_pats,
        res_buf, pid_buf, MAX_RESULTS,
        ctypes.byref(dur),
    )

    if count < 0:
        raise MemoryError("apme_aho_corasick: C allocation failed")

    filled = min(count, MAX_RESULTS)

    # Group results by pattern index
    per_pattern: dict[int, list[int]] = {i: [] for i in range(n_pats)}
    for k in range(filled):
        per_pattern[pid_buf[k]].append(res_buf[k])

    out: dict[str, SearchResult] = {}
    for i, pat_b in enumerate(pats_b):
        key = pat_b.decode("utf-8", errors="replace")
        out[key] = SearchResult(per_pattern[i], dur.value, "AHO-CORASICK", count)

    return out


def search_fuzzy(
    text: str | bytes,
    pattern: str | bytes,
    max_errors: int = 1,
) -> SearchResult:
    """
    Approximate (fuzzy) search.  max_errors is the Levenshtein distance budget.
    Returned indices are END byte offsets of each approximate match.
    """
    lib     = get_lib()
    text_b  = _encode(text)
    pat_b   = _encode(pattern)
    t_len   = len(text_b)
    p_len   = len(pat_b)
    buf     = _make_buf(MAX_RESULTS)
    dur     = ctypes.c_double(0.0)

    count = lib.apme_fuzzy(
        text_b, t_len, pat_b, p_len, max_errors, buf, MAX_RESULTS, ctypes.byref(dur)
    )

    if count < 0:
        raise MemoryError("apme_fuzzy: C allocation failed")

    filled  = min(count, MAX_RESULTS)
    matches = list(buf[:filled])
    return SearchResult(matches, dur.value, f"FUZZY(k={max_errors})", count)


def engine_version() -> str:
    return get_lib().apme_version().decode()
