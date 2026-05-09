"""
Parallel and streaming search over large text corpora.

Two execution paths
───────────────────
ThreadedSearcher  — splits an in-memory bytes buffer into chunks and searches
                    them concurrently using a ThreadPoolExecutor.  ctypes calls
                    release the GIL, so true parallelism is achieved without the
                    pickling overhead of multiprocessing.

StreamingSearcher — reads a file one chunk at a time (constant memory) and
                    searches sequentially.  Used when the file is too large to
                    load into RAM (> STREAMING_THRESHOLD).
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Callable

from app.engine import wrapper as _w
from app.processing.chunker import (
    Chunk,
    DEFAULT_CHUNK_SIZE,
    filter_chunk_matches,
    iter_file_chunks,
    split_bytes_into_chunks,
)

STREAMING_THRESHOLD = 50 * 1024 * 1024   # 50 MB — switch to streaming
MAX_WORKERS = min(8, (os.cpu_count() or 4))

# Map algorithm name → wrapper function
_ALG_MAP: dict[str, Callable] = {
    "KMP":          _w.search_kmp,
    "Boyer-Moore":  _w.search_boyer_moore,
    "Rabin-Karp":   _w.search_rabin_karp,
    "Shift-Or":     _w.search_shift_or,
}


@dataclass
class ParallelResult:
    matches:       list[int]        # absolute byte offsets, sorted
    duration_ms:   float            # wall-clock time for the whole search
    algorithm:     str
    chunks_used:   int
    total_bytes:   int
    truncated:     bool = False


# ── per-chunk worker (called inside a thread) ─────────────────────────────────

def _search_chunk(
    chunk: Chunk,
    pattern: bytes,
    search_fn: Callable,
) -> list[int]:
    result = search_fn(chunk.data, pattern)
    return filter_chunk_matches(result.matches, chunk)


# ── Threaded searcher ─────────────────────────────────────────────────────────

class ThreadedSearcher:
    """
    Parallel in-memory search.  Best for files that fit in RAM (≤ 50 MB).
    """

    def __init__(
        self,
        max_workers: int = MAX_WORKERS,
        chunk_size:  int = DEFAULT_CHUNK_SIZE,
    ):
        self.max_workers = max_workers
        self.chunk_size  = chunk_size

    def search(
        self,
        data:      bytes,
        pattern:   bytes,
        algorithm: str = "Boyer-Moore",
    ) -> ParallelResult:

        search_fn = _ALG_MAP.get(algorithm, _ALG_MAP["Boyer-Moore"])
        chunks    = split_bytes_into_chunks(data, len(pattern), self.chunk_size)

        t0  = time.perf_counter()
        all_matches: list[int] = []

        if len(chunks) == 1:
            # Single chunk — no threading overhead
            all_matches = _search_chunk(chunks[0], pattern, search_fn)
        else:
            futures = {}
            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                for chunk in chunks:
                    fut = pool.submit(_search_chunk, chunk, pattern, search_fn)
                    futures[fut] = chunk

            for fut in as_completed(futures):
                all_matches.extend(fut.result())

        all_matches.sort()
        elapsed = (time.perf_counter() - t0) * 1000

        return ParallelResult(
            matches=all_matches,
            duration_ms=elapsed,
            algorithm=algorithm,
            chunks_used=len(chunks),
            total_bytes=len(data),
        )


# ── Streaming searcher ────────────────────────────────────────────────────────

class StreamingSearcher:
    """
    Sequential streaming search for very large files (> 50 MB).
    Memory usage is bounded to ~(chunk_size + pattern_len) bytes.
    """

    def __init__(self, chunk_size: int = DEFAULT_CHUNK_SIZE):
        self.chunk_size = chunk_size

    def search_file(
        self,
        file_path: str,
        pattern:   bytes,
        algorithm: str = "Boyer-Moore",
        max_matches: int = 0,           # 0 = unlimited
    ) -> ParallelResult:

        search_fn  = _ALG_MAP.get(algorithm, _ALG_MAP["Boyer-Moore"])
        t0         = time.perf_counter()
        all_matches: list[int] = []
        chunk_count = 0
        total_bytes = os.path.getsize(file_path)
        done        = False

        for chunk in iter_file_chunks(file_path, len(pattern), self.chunk_size):
            chunk_count += 1
            hits = _search_chunk(chunk, pattern, search_fn)
            all_matches.extend(hits)
            if max_matches and len(all_matches) >= max_matches:
                done = True
                break

        all_matches.sort()
        elapsed = (time.perf_counter() - t0) * 1000

        return ParallelResult(
            matches=all_matches[:max_matches] if max_matches else all_matches,
            duration_ms=elapsed,
            algorithm=algorithm,
            chunks_used=chunk_count,
            total_bytes=total_bytes,
            truncated=done,
        )


# ── Convenience factory ───────────────────────────────────────────────────────

def search_large_file(
    file_path:   str,
    pattern:     bytes,
    algorithm:   str = "Boyer-Moore",
    max_matches: int = 0,
) -> ParallelResult:
    """
    Automatically pick threaded vs. streaming based on file size.
    """
    size = os.path.getsize(file_path)

    if size > STREAMING_THRESHOLD:
        searcher = StreamingSearcher()
        return searcher.search_file(file_path, pattern, algorithm, max_matches)

    with open(file_path, "rb") as fh:
        data = fh.read()

    searcher = ThreadedSearcher()
    return searcher.search(data, pattern, algorithm)
