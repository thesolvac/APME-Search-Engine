"""
APME Search Engine — main orchestrator.

APMESearchEngine is the single entry point for all search operations.
It wires together:
  • Heuristic algorithm selection   (app.processing.heuristics)
  • Parallel / streaming execution   (app.processing.parallel_search)
  • C-backed exact algorithms        (app.engine.wrapper)
  • Named-entity enrichment          (app.processing.ner)
  • Real-time file monitoring        (app.processing.monitor)
  • MongoDB persistence              (app.models.*)

All public methods return plain dicts so they can be JSON-serialised directly
by Flask routes.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable, Sequence

from app.engine import wrapper as _w
from app.processing.heuristics import (
    TextProfile,
    explain_selection,
    profile_text,
    select_algorithm,
)
from app.processing.ner import enrich_match, extract_entities
from app.processing.parallel_search import (
    STREAMING_THRESHOLD,
    ThreadedSearcher,
    search_large_file,
)
from app.processing.monitor import FileMonitor, MonitorEvent

# ── Optional MongoDB (graceful degradation if DB is unavailable) ──────────────
try:
    from app.models.search_history   import SearchHistoryModel
    from app.models.performance_log  import PerformanceLogModel
    _DB_AVAILABLE = True
except Exception:
    _DB_AVAILABLE = False

_ALG_FN = {
    "KMP":          _w.search_kmp,
    "Boyer-Moore":  _w.search_boyer_moore,
    "Rabin-Karp":   _w.search_rabin_karp,
    "Shift-Or":     _w.search_shift_or,
}

# Bytes returned as context around each match in the enriched view
_CONTEXT_CHARS = 120


# ── Result helpers ────────────────────────────────────────────────────────────

def _make_result(
    matches:     list[int],
    duration_ms: float,
    algorithm:   str,
    pattern_len: int,
    text:        str | None = None,
    enrich:      bool = False,
    max_enrich:  int = 50,
) -> dict:
    result: dict = {
        "matches":      matches,
        "match_count":  len(matches),
        "algorithm":    algorithm,
        "duration_ms":  round(duration_ms, 4),
        "pattern_len":  pattern_len,
    }
    if enrich and text and matches:
        result["enriched"] = [
            enrich_match(text, pos, pattern_len, _CONTEXT_CHARS)
            for pos in matches[:max_enrich]
        ]
    return result


# ── Main engine class ─────────────────────────────────────────────────────────

class APMESearchEngine:
    """
    Stateful engine instance.  Create one per Flask application (or per request
    for stateless use).

    Parameters
    ----------
    enable_db   : persist search history / performance logs to MongoDB
    parallel    : use multi-threaded chunked search for large in-memory texts
    enrich_ner  : attach NER-enriched context snippets to results
    max_enrich  : max matches to enrich (NER is O(n) per snippet)
    """

    def __init__(
        self,
        enable_db:   bool = True,
        parallel:    bool = True,
        enrich_ner:  bool = False,
        max_enrich:  int  = 50,
    ):
        self.enable_db  = enable_db and _DB_AVAILABLE
        self.parallel   = parallel
        self.enrich_ner = enrich_ner
        self.max_enrich = max_enrich
        self._monitor   = FileMonitor()
        self._threaded  = ThreadedSearcher()

    # ── Core search ───────────────────────────────────────────────────────────

    def search(
        self,
        source:    str | bytes | Path,
        pattern:   str | bytes,
        algorithm: str = "AUTO",
        user_id:   str = "",
        fuzzy:     bool = False,
        max_errors: int = 1,
    ) -> dict:
        """
        Universal search entry point.

        Parameters
        ----------
        source    : file path (str/Path) OR raw text (bytes/str)
        pattern   : search pattern
        algorithm : 'AUTO' lets the heuristic choose; or specify one explicitly
        user_id   : for search-history logging
        fuzzy     : use approximate matching (ignores algorithm)
        max_errors: edit-distance budget for fuzzy search
        """
        pat_bytes  = pattern.encode("utf-8") if isinstance(pattern, str) else pattern
        is_file    = isinstance(source, (str, Path)) and os.path.isfile(str(source))
        text_str   = None   # decoded text (for NER enrichment)

        # ── Load data ────────────────────────────────────────────────────────
        if is_file:
            file_path  = str(source)
            file_size  = os.path.getsize(file_path)
            sample_len = min(file_size, 65_536)
            with open(file_path, "rb") as fh:
                sample = fh.read(sample_len)
            source_label = os.path.basename(file_path)
        else:
            data       = source.encode("utf-8") if isinstance(source, str) else source
            text_str   = source if isinstance(source, str) else source.decode("utf-8", errors="replace")
            file_path  = ""
            file_size  = len(data)
            sample     = data[:65_536]
            source_label = "<inline text>"

        # ── Fuzzy path ───────────────────────────────────────────────────────
        if fuzzy:
            if is_file:
                with open(file_path, "rb") as fh:
                    data = fh.read()
            result = _w.search_fuzzy(data, pat_bytes, max_errors=max_errors)
            out = _make_result(
                result.matches, result.duration_ms, result.algorithm,
                len(pat_bytes), text_str, self.enrich_ner, self.max_enrich,
            )
            self._log(out, pat_bytes, [source_label], user_id, file_size)
            return out

        # ── Algorithm selection ───────────────────────────────────────────────
        if algorithm.upper() == "AUTO":
            alg = select_algorithm(pat_bytes, text_sample=sample, text_len=file_size)
            out_alg_note = explain_selection(alg, pat_bytes, sample, file_size)
        else:
            alg = algorithm
            out_alg_note = "manual"

        # ── Execute search ───────────────────────────────────────────────────
        if is_file:
            pr = search_large_file(file_path, pat_bytes, alg)
            matches     = pr.matches
            duration_ms = pr.duration_ms
        else:
            if self.parallel and file_size > 1 * 1024 * 1024:
                pr = self._threaded.search(data, pat_bytes, alg)
                matches     = pr.matches
                duration_ms = pr.duration_ms
            else:
                fn = _ALG_FN.get(alg, _ALG_FN["Boyer-Moore"])
                sr = fn(data, pat_bytes)
                matches     = sr.matches
                duration_ms = sr.duration_ms

        out = _make_result(
            matches, duration_ms, alg,
            len(pat_bytes), text_str, self.enrich_ner, self.max_enrich,
        )
        out["algorithm_note"] = out_alg_note
        self._log(out, pat_bytes, [source_label], user_id, file_size)
        return out

    # ── Multi-pattern ─────────────────────────────────────────────────────────

    def search_multi(
        self,
        source:   str | bytes | Path,
        patterns: Sequence[str | bytes],
        user_id:  str = "",
    ) -> dict:
        """
        Search for multiple patterns simultaneously using Aho-Corasick.
        Returns a dict keyed by pattern string.
        """
        is_file = isinstance(source, (str, Path)) and os.path.isfile(str(source))
        if is_file:
            with open(str(source), "rb") as fh:
                data = fh.read()
        else:
            data = source.encode("utf-8") if isinstance(source, str) else source

        t0 = time.perf_counter()
        ac_results = _w.search_aho_corasick(data, patterns)
        elapsed = (time.perf_counter() - t0) * 1000

        out: dict = {"algorithm": "Aho-Corasick", "duration_ms": round(elapsed, 4), "results": {}}
        for pat, sr in ac_results.items():
            out["results"][pat] = {
                "matches":     sr.matches,
                "match_count": len(sr.matches),
            }
        return out

    # ── NER standalone ────────────────────────────────────────────────────────

    def extract_entities(self, text: str) -> list[dict]:
        """Run NER on arbitrary text.  Returns serialisable list of dicts."""
        entities = extract_entities(text)
        return [{"type": e.type, "value": e.value,
                 "start": e.start, "end": e.end} for e in entities]

    # ── File monitoring ───────────────────────────────────────────────────────

    def start_monitoring(
        self,
        path:      str | Path,
        pattern:   str | bytes,
        callback:  Callable[[dict], None],
        algorithm: str = "KMP",
    ) -> str:
        """
        Start watching *path*.  On every file change with new matches,
        *callback* is called with a serialisable dict.

        Returns watch_id (str).
        """
        def _wrapped(mon_event: MonitorEvent):
            callback({
                "watch_id":    mon_event.watch_id,
                "file":        mon_event.file_path,
                "new_matches": mon_event.matches,
                "all_matches": mon_event.all_matches,
                "timestamp":   mon_event.timestamp,
                "error":       mon_event.error,
            })

        return self._monitor.watch(path, pattern, _wrapped, algorithm)

    def stop_monitoring(self, watch_id: str | None = None):
        """Stop one watch (by watch_id) or all watches if watch_id is None."""
        if watch_id:
            self._monitor.stop(watch_id)
        else:
            self._monitor.stop_all()

    def active_watches(self) -> list[str]:
        return self._monitor.active_watches()

    # ── Private helpers ───────────────────────────────────────────────────────

    def _log(
        self,
        result:       dict,
        pattern:      bytes,
        files:        list[str],
        user_id:      str,
        text_size:    int,
    ):
        if not self.enable_db:
            return
        try:
            SearchHistoryModel.create(
                user_id=user_id or "anonymous",
                query=pattern.decode("utf-8", errors="replace"),
                algorithm=result.get("algorithm", ""),
                files=files,
                matches_count=result.get("match_count", 0),
                duration_ms=result.get("duration_ms", 0.0),
            )
            PerformanceLogModel.create(
                algorithm=result.get("algorithm", ""),
                file_path=files[0] if files else "",
                text_size_bytes=text_size,
                duration_ms=result.get("duration_ms", 0.0),
                matches_count=result.get("match_count", 0),
                user_id=user_id or "anonymous",
            )
        except Exception:
            pass   # DB logging is best-effort; never crash a search


# ── Module-level singleton ────────────────────────────────────────────────────

_engine: APMESearchEngine | None = None


def get_engine(**kwargs) -> APMESearchEngine:
    """Return the application-level singleton (created on first call)."""
    global _engine
    if _engine is None:
        _engine = APMESearchEngine(**kwargs)
    return _engine
