"""
Search blueprint — /api/search

POST /text          search plain text submitted in request body
POST /file          upload a text file and search it
POST /multi         multi-pattern Aho-Corasick search
POST /compare       run all algorithms in parallel, return timing comparison
GET  /autocomplete  query-prefix autocomplete from search history
"""

from __future__ import annotations

import concurrent.futures
import os
import tempfile
from pathlib import Path

from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.engine import wrapper as _w
from app.models.document import DocumentModel
from app.models.search_history import SearchHistoryModel
from app.processing.heuristics import select_algorithm
from app.search_engine import get_engine
from app.utils.decorators import login_required
from app.utils.responses import error, success

search_bp = Blueprint("search", __name__, url_prefix="/api/search")

_ALLOWED_EXTENSIONS = {
    ".txt", ".log", ".csv", ".tsv", ".md",
    ".json", ".xml", ".html", ".py", ".js",
}
_MAX_COMPARE_BYTES = 5_000_000   # 5 MB cap for compare endpoint
_MAX_AUTOCOMPLETE  = 15

_ALG_FNS = {
    "KMP":         _w.search_kmp,
    "Boyer-Moore": _w.search_boyer_moore,
    "Rabin-Karp":  _w.search_rabin_karp,
    "Shift-Or":    _w.search_shift_or,
}


def _allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in _ALLOWED_EXTENSIONS


# ── Text search ───────────────────────────────────────────────────────────────

@search_bp.post("/text")
@login_required
def search_text():
    """Search a plain-text body submitted as JSON."""
    body      = request.get_json(silent=True) or {}
    text      = body.get("text", "")
    pattern   = body.get("pattern", "")
    algorithm = body.get("algorithm", "AUTO")
    fuzzy     = bool(body.get("fuzzy", False))
    max_errors = int(body.get("max_errors", 1))
    enrich    = bool(body.get("enrich", False))

    if not text:
        return error("'text' is required", 400)
    if not pattern:
        return error("'pattern' is required", 400)

    user_id = get_jwt_identity()
    engine  = get_engine(enable_db=True, parallel=True, enrich_ner=enrich)
    result  = engine.search(
        text, pattern,
        algorithm=algorithm,
        user_id=user_id,
        fuzzy=fuzzy,
        max_errors=max_errors,
    )
    return success(result, "Search complete")


# ── File upload search ────────────────────────────────────────────────────────

@search_bp.post("/file")
@login_required
def search_file():
    """Upload a text file (multipart/form-data) and search it."""
    if "file" not in request.files:
        return error("No 'file' part in request", 400)

    f = request.files["file"]
    if not f.filename:
        return error("No file selected", 400)
    if not _allowed_file(f.filename):
        exts = ", ".join(sorted(_ALLOWED_EXTENSIONS))
        return error(f"File type not allowed. Accepted: {exts}", 400)

    pattern    = request.form.get("pattern", "")
    algorithm  = request.form.get("algorithm", "AUTO")
    fuzzy      = request.form.get("fuzzy", "false").lower() == "true"
    max_errors = int(request.form.get("max_errors", 1))

    if not pattern:
        return error("'pattern' is required", 400)

    user_id = get_jwt_identity()
    suffix  = Path(f.filename).suffix or ".txt"

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
        f.save(tmp_path)

    try:
        file_size = os.path.getsize(tmp_path)
        DocumentModel.create(
            file_name=f.filename,
            file_path=tmp_path,
            size_bytes=file_size,
            uploaded_by=user_id,
        )

        engine = get_engine(enable_db=True, parallel=True)
        result = engine.search(
            tmp_path, pattern,
            algorithm=algorithm,
            user_id=user_id,
            fuzzy=fuzzy,
            max_errors=max_errors,
        )
        result["file_name"]       = f.filename
        result["file_size_bytes"] = file_size
        return success(result, "File search complete")
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# ── Multi-pattern search ──────────────────────────────────────────────────────

@search_bp.post("/multi")
@login_required
def search_multi():
    """Multi-pattern simultaneous search using Aho-Corasick."""
    body     = request.get_json(silent=True) or {}
    text     = body.get("text", "")
    patterns = body.get("patterns", [])

    if not text:
        return error("'text' is required", 400)
    if not patterns or not isinstance(patterns, list):
        return error("'patterns' must be a non-empty list", 400)
    if len(patterns) > 50:
        return error("Maximum 50 patterns per request", 400)

    user_id = get_jwt_identity()
    engine  = get_engine(enable_db=True)
    result  = engine.search_multi(text, patterns, user_id=user_id)
    return success(result, "Multi-pattern search complete")


# ── Comparative algorithm analysis ────────────────────────────────────────────

@search_bp.post("/compare")
@login_required
def compare_algorithms():
    """
    Run KMP, Boyer-Moore, Rabin-Karp, and Shift-Or on the same input in
    parallel threads.  Returns a timing comparison and highlights which
    algorithm AUTO would have chosen and which was actually fastest.
    """
    body    = request.get_json(silent=True) or {}
    text    = body.get("text", "")
    pattern = body.get("pattern", "")

    if not text:
        return error("'text' is required", 400)
    if not pattern:
        return error("'pattern' is required", 400)

    data = text.encode("utf-8") if isinstance(text, str) else text
    if len(data) > _MAX_COMPARE_BYTES:
        return error(f"Text too large for comparison (max {_MAX_COMPARE_BYTES // 1_000_000} MB)", 400)

    pat = pattern.encode("utf-8") if isinstance(pattern, str) else pattern

    auto_choice = select_algorithm(pat, text_sample=data[:65_536], text_len=len(data))

    def _run(name: str, fn) -> tuple[str, dict]:
        sr = fn(data, pat)
        return name, {
            "duration_ms": round(sr.duration_ms, 4),
            "match_count": len(sr.matches),
        }

    comparison: dict[str, dict] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        futs = {pool.submit(_run, name, fn): name for name, fn in _ALG_FNS.items()}
        for fut in concurrent.futures.as_completed(futs):
            name, stats = fut.result()
            comparison[name] = stats

    fastest = min(comparison, key=lambda k: comparison[k]["duration_ms"])
    for alg, stats in comparison.items():
        stats["auto_selected"] = (alg == auto_choice)
        stats["is_fastest"]    = (alg == fastest)

    return success({
        "pattern":      pattern,
        "text_length":  len(text),
        "auto_selected": auto_choice,
        "fastest":       fastest,
        "comparison":    comparison,
    }, "Comparison complete")


# ── Autocomplete ──────────────────────────────────────────────────────────────

@search_bp.get("/autocomplete")
@login_required
def autocomplete():
    """Return query-prefix autocomplete suggestions from search history."""
    q     = request.args.get("q", "").strip()
    limit = min(int(request.args.get("limit", 10)), _MAX_AUTOCOMPLETE)
    scope = request.args.get("scope", "me")   # "me" | "global"

    if not q:
        return success([], "No prefix provided")

    user_id     = get_jwt_identity() if scope == "me" else ""
    suggestions = SearchHistoryModel.autocomplete(q, user_id=user_id, limit=limit)
    return success(suggestions, f"{len(suggestions)} suggestion(s)")
