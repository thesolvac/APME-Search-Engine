"""
File-reading utilities that split text into overlapping chunks
for parallel or streaming search.

Overlap strategy
────────────────
When a text is split at byte offset S, a pattern of length m could start at
byte S - m + 1 and end at byte S + m - 2.  To guarantee such matches are found,
each chunk extends (m - 1) bytes past its logical boundary into the next chunk.
After searching, only matches whose START position falls within the logical
[chunk_start, chunk_end) range are accepted.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Generator, Iterator

DEFAULT_CHUNK_SIZE = 4 * 1024 * 1024   # 4 MB


@dataclass(frozen=True)
class Chunk:
    data:        bytes   # bytes to search (may be longer than logical window)
    logical_start: int   # absolute byte offset where this chunk's results begin
    logical_end:   int   # absolute byte offset where this chunk's results end (exclusive)
    index:         int   # chunk number (0-based)


def iter_file_chunks(
    file_path: str,
    pattern_len: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> Generator[Chunk, None, None]:
    """
    Yield overlapping Chunk objects by reading the file sequentially.
    Memory usage is bounded to ~(chunk_size + pattern_len) bytes at a time.
    """
    overlap = max(0, pattern_len - 1)
    file_size = os.path.getsize(file_path)

    with open(file_path, "rb") as fh:
        logical_start = 0
        chunk_idx = 0

        while logical_start < file_size:
            logical_end = min(logical_start + chunk_size, file_size)

            # Read the logical range + overlap extension into the next chunk
            read_end = min(logical_end + overlap, file_size)
            fh.seek(logical_start)
            data = fh.read(read_end - logical_start)

            yield Chunk(data, logical_start, logical_end, chunk_idx)

            logical_start = logical_end
            chunk_idx += 1


def split_bytes_into_chunks(
    data: bytes,
    pattern_len: int,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> list[Chunk]:
    """
    Split an in-memory bytes object into overlapping Chunk objects.
    Used when the file already fits in RAM.
    """
    overlap = max(0, pattern_len - 1)
    n = len(data)
    chunks: list[Chunk] = []
    logical_start = 0
    idx = 0

    while logical_start < n:
        logical_end = min(logical_start + chunk_size, n)
        read_end    = min(logical_end + overlap, n)
        chunk_data  = data[logical_start:read_end]
        chunks.append(Chunk(chunk_data, logical_start, logical_end, idx))
        logical_start = logical_end
        idx += 1

    return chunks


def filter_chunk_matches(raw_matches: list[int], chunk: Chunk) -> list[int]:
    """
    Convert raw (relative-to-chunk) match positions to absolute byte offsets,
    keeping only matches whose start falls in the chunk's logical window.
    """
    absolute: list[int] = []
    logical_len = chunk.logical_end - chunk.logical_start
    for rel_pos in raw_matches:
        if rel_pos < logical_len:                         # inside logical window
            absolute.append(chunk.logical_start + rel_pos)
    return absolute
