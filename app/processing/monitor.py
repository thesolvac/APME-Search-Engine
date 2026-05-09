"""
Real-time file monitoring using watchdog.

Usage
─────
    from app.processing.monitor import FileMonitor

    def on_hit(event):
        print(f"[MONITOR] {event}")

    monitor = FileMonitor()
    watch_id = monitor.watch(
        path="/var/log/app.log",
        pattern=b"ERROR",
        callback=on_hit,
        algorithm="KMP",
    )
    # ... later ...
    monitor.stop(watch_id)
    monitor.stop_all()

The callback receives a MonitorEvent dataclass on every change that yields
at least one new match.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent
from watchdog.observers import Observer

from app.engine import wrapper as _w

_ALG_MAP = {
    "KMP":         _w.search_kmp,
    "Boyer-Moore": _w.search_boyer_moore,
    "Rabin-Karp":  _w.search_rabin_karp,
    "Shift-Or":    _w.search_shift_or,
}


# ── Public data structures ────────────────────────────────────────────────────

@dataclass
class MonitorEvent:
    watch_id:    str
    file_path:   str
    pattern:     bytes
    algorithm:   str
    matches:     list[int]   # absolute byte offsets of NEW matches
    all_matches: list[int]   # all current matches in the file
    timestamp:   float = field(default_factory=time.time)
    error:       str   = ""


# ── Internal watch state ──────────────────────────────────────────────────────

@dataclass
class _WatchState:
    watch_id:    str
    file_path:   str
    pattern:     bytes
    algorithm:   str
    callback:    Callable[[MonitorEvent], None]
    prev_matches: set[int] = field(default_factory=set)
    _lock:       threading.Lock = field(default_factory=threading.Lock)

    def run_search(self) -> MonitorEvent:
        try:
            with open(self.file_path, "rb") as fh:
                data = fh.read()
        except OSError as exc:
            return MonitorEvent(
                self.watch_id, self.file_path, self.pattern,
                self.algorithm, [], [], error=str(exc),
            )

        search_fn = _ALG_MAP.get(self.algorithm, _ALG_MAP["Boyer-Moore"])
        result = search_fn(data, self.pattern)
        current = set(result.matches)

        with self._lock:
            new_matches = sorted(current - self.prev_matches)
            self.prev_matches = current

        return MonitorEvent(
            watch_id=self.watch_id,
            file_path=self.file_path,
            pattern=self.pattern,
            algorithm=self.algorithm,
            matches=new_matches,
            all_matches=sorted(current),
        )


# ── Watchdog event handler ────────────────────────────────────────────────────

class _APMEEventHandler(FileSystemEventHandler):
    def __init__(self, watch_state: _WatchState):
        super().__init__()
        self._state = watch_state

    def _handle(self, event_path: str):
        # Normalise and compare paths
        if os.path.abspath(event_path) != os.path.abspath(self._state.file_path):
            return
        mon_event = self._state.run_search()
        if mon_event.matches or mon_event.error:
            try:
                self._state.callback(mon_event)
            except Exception:
                pass   # never let a callback crash the observer thread

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)


# ── Public monitor class ──────────────────────────────────────────────────────

class FileMonitor:
    """
    Manages multiple watchdog observers.  Each watch targets a single file.
    Thread-safe.
    """

    def __init__(self):
        self._watches:   dict[str, tuple[_WatchState, Observer]] = {}
        self._lock = threading.Lock()

    def watch(
        self,
        path:      str | Path,
        pattern:   bytes | str,
        callback:  Callable[[MonitorEvent], None],
        algorithm: str = "KMP",
    ) -> str:
        """
        Start monitoring *path*.  Returns a watch_id that can be passed to
        stop().

        Parameters
        ----------
        path      : absolute or relative path to the file to watch
        pattern   : search pattern (str → encoded as UTF-8)
        callback  : called with a MonitorEvent whenever new matches appear
        algorithm : one of KMP / Boyer-Moore / Rabin-Karp / Shift-Or
        """
        if isinstance(pattern, str):
            pattern = pattern.encode("utf-8")
        if isinstance(path, Path):
            path = str(path)
        path = os.path.abspath(path)

        watch_id = str(uuid.uuid4())
        state    = _WatchState(watch_id, path, pattern, algorithm, callback)

        # Run an initial search so prev_matches is populated
        state.run_search()

        handler  = _APMEEventHandler(state)
        observer = Observer()
        observer.schedule(handler, path=os.path.dirname(path), recursive=False)
        observer.start()

        with self._lock:
            self._watches[watch_id] = (state, observer)

        return watch_id

    def stop(self, watch_id: str) -> bool:
        """Stop a single watch.  Returns True if the watch existed."""
        with self._lock:
            entry = self._watches.pop(watch_id, None)
        if entry:
            _, observer = entry
            observer.stop()
            observer.join(timeout=5)
            return True
        return False

    def stop_all(self):
        """Stop every active watch."""
        with self._lock:
            ids = list(self._watches.keys())
        for wid in ids:
            self.stop(wid)

    def active_watches(self) -> list[str]:
        with self._lock:
            return list(self._watches.keys())

    def __del__(self):
        self.stop_all()
