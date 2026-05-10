# APME Search Engine — System Architecture

## Table of Contents

1. [Overview](#overview)
2. [Directory Structure](#directory-structure)
3. [Layer Architecture](#layer-architecture)
4. [C Engine Layer](#c-engine-layer)
5. [Python Wrapper](#python-wrapper)
6. [Heuristic Algorithm Selector](#heuristic-algorithm-selector)
7. [Parallel & Streaming Search](#parallel--streaming-search)
8. [Flask API](#flask-api)
9. [Frontend Architecture](#frontend-architecture)
10. [Data Flow](#data-flow)
11. [MongoDB Schema](#mongodb-schema)
12. [Authentication & Authorization](#authentication--authorization)
13. [Algorithm Selection Table](#algorithm-selection-table)
14. [Deployment Notes](#deployment-notes)

---

## Overview

APME (Adaptive Pattern Matching Engine) is a full-stack text search system that exposes
six string-matching algorithms through a REST API backed by a compiled C shared library.

Design goals:
- **Performance**: All hot-path matching runs in native C, released from the Python GIL.
- **Adaptivity**: A rule-based heuristic selects the optimal algorithm automatically.
- **Scale**: Parallel chunked search for large in-memory texts; memory-mapped streaming
  for files that exceed available RAM.
- **No ML**: Every decision (algorithm selection, recommendations) is deterministic and
  rule-based. The system produces reproducible results with no training dependency.

---

## Directory Structure

```
APME-Search-Engine/
├── c_engine/
│   ├── apme_engine.h        # Public C API — all six algorithms declared here
│   ├── apme_engine.c        # Implementation (KMP, BM, RK, Shift-Or, AC, Fuzzy)
│   └── build.py             # Compiles to apme_engine.dll / apme_engine.so
│
├── app/
│   ├── __init__.py          # Flask application factory, blueprint registration
│   ├── search_engine.py     # APMESearchEngine orchestrator (singleton)
│   │
│   ├── engine/
│   │   ├── loader.py        # ctypes DLL loader with lazy initialisation
│   │   └── wrapper.py       # Python API over the C library
│   │
│   ├── processing/
│   │   ├── heuristics.py    # Rule-based algorithm selector + text profiler
│   │   ├── parallel_search.py  # ThreadedSearcher, StreamingSearcher
│   │   ├── ner.py           # Named-entity recognition (rule-based)
│   │   └── monitor.py       # Real-time file watcher (watchdog)
│   │
│   ├── models/
│   │   ├── user.py          # Users collection (bcrypt passwords)
│   │   ├── document.py      # Uploaded file records
│   │   ├── search_history.py   # Per-user search log + aggregations
│   │   └── performance_log.py  # Per-algorithm timing log + aggregations
│   │
│   ├── routes/
│   │   ├── auth.py          # POST /register, /login; GET /me; PUT /change-password
│   │   ├── search.py        # POST /text, /file, /multi, /compare; GET /autocomplete, /history
│   │   ├── stats.py         # GET /me, /algorithms, /trending, /recommendations
│   │   ├── admin.py         # CRUD /users; GET /search-history, /performance-logs
│   │   └── views.py         # Server-side HTML page routes
│   │
│   ├── utils/
│   │   ├── decorators.py    # @login_required, @admin_required
│   │   └── responses.py     # success() / error() JSON envelope helpers
│   │
│   ├── static/
│   │   ├── js/
│   │   │   ├── api.js       # Fetch wrapper, JWT management, shared utilities
│   │   │   ├── auth.js      # Login / register page logic
│   │   │   ├── dashboard.js # User dashboard: stats, charts, history
│   │   │   ├── search.js    # Search interface: autocomplete, file upload, trending
│   │   │   ├── results.js   # Results page: highlighting, NER, compare chart
│   │   │   └── admin.js     # Admin panel: user CRUD table
│   │   └── css/
│   │       └── custom.css   # Supplementary styles (Tailwind CDN handles the rest)
│   │
│   └── templates/
│       ├── base.html        # Shared layout: nav, toast, skeleton CSS, Tailwind CDN
│       ├── index.html       # Landing / hero page
│       ├── login.html       # Login + register tabs
│       ├── dashboard.html   # User dashboard
│       ├── search.html      # Search interface
│       ├── results.html     # Results viewer
│       └── admin.html       # Admin panel
│
├── tests/
│   ├── test_phase1.py       # C library unit tests (ctypes direct calls)
│   ├── test_phase2.py       # Python wrapper + heuristics tests
│   ├── test_phase3.py       # Parallel search + NER tests
│   └── test_phase4.py       # Flask API endpoint integration tests
│
├── config.py                # Flask / MongoDB / JWT configuration
├── run.py                   # Development server entry point
└── ARCHITECTURE.md          # This file
```

---

## Layer Architecture

```
┌────────────────────────────────────────────────────────────┐
│  Browser  (Tailwind CSS · Vanilla JS ES2020 · JWT)         │
└───────────────────────────┬────────────────────────────────┘
                            │  HTTP / JSON
┌───────────────────────────▼────────────────────────────────┐
│  Flask API  (Blueprints: auth · search · stats · admin)    │
│  JWT authentication · @login_required · @admin_required    │
└──────┬──────────────────────────────────┬──────────────────┘
       │                                  │
┌──────▼───────┐                 ┌────────▼────────┐
│ APMESearch   │                 │   MongoDB        │
│ Engine       │                 │  (pymongo)       │
│ (singleton)  │                 │  users           │
│              │                 │  documents       │
│ heuristics   │                 │  search_history  │
│ parallel     │                 │  performance_log │
│ ner          │                 └─────────────────┘
│ monitor      │
└──────┬───────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│  Python Wrapper  (ctypes · argtypes · restype · GIL-free)   │
└──────┬──────────────────────────────────────────────────────┘
       │
┌──────▼──────────────────────────────────────────────────────┐
│  C Shared Library  (apme_engine.dll / apme_engine.so)       │
│  KMP · Boyer-Moore · Rabin-Karp · Shift-Or                  │
│  Aho-Corasick · Wu-Manber Fuzzy                             │
└────────────────────────────────────────────────────────────┘
```

---

## C Engine Layer

**File**: `c_engine/apme_engine.c` / `apme_engine.h`

The C library is compiled once and loaded at Python startup via `ctypes.CDLL`.
All six search functions share a common return convention:

| Return value | Meaning |
|---|---|
| `>= 0` | Total match count. `results[]` filled up to `max_results`. |
| `-1` | Internal `malloc` failure. |

All indices are **byte offsets** into the text buffer. Fuzzy search reports the
**end** offset of each match window; all other algorithms report the **start** offset.

Timing uses `QueryPerformanceCounter` on Windows and `clock_gettime(CLOCK_MONOTONIC)`
on POSIX, written to `*duration_ms` as a `double`.

### Algorithms

| Function | Algorithm | Best case | Worst case | Space |
|---|---|---|---|---|
| `apme_kmp` | Knuth-Morris-Pratt | O(n+m) | O(n+m) | O(m) |
| `apme_boyer_moore` | Boyer-Moore (BC+GS) | O(n/m) | O(nm) | O(σ+m) |
| `apme_rabin_karp` | Rabin-Karp double hash | O(n+m) avg | O(nm) | O(1) |
| `apme_shift_or` | Shift-Or / Bitap | O(n) for m≤64 | O(n·⌈m/64⌉) | O(σ) |
| `apme_aho_corasick` | Aho-Corasick automaton | O(n+Σmᵢ+k) | O(n+Σmᵢ+k) | O(σ·\|trie\|) |
| `apme_fuzzy` | Wu-Manber k-error Bitap | O(n·k) | O(n·m) fallback | O(k) |

**n** = text length, **m** = pattern length, **σ** = alphabet size (256), **k** = max errors, **k** = match count.

Shift-Or automatically falls back to KMP for patterns longer than 64 bytes.
Fuzzy search falls back from Wu-Manber Bitap to Levenshtein DP for patterns longer than 64 bytes.

---

## Python Wrapper

**File**: `app/engine/wrapper.py`

`get_lib()` (in `loader.py`) performs lazy DLL loading and calls `_setup_signatures()` once,
which sets `argtypes` and `restype` on every C function. This enables type checking and
ensures ctypes passes the correct types to C without silent truncation.

All public functions accept `str | bytes` and encode to UTF-8 internally. They return a
`SearchResult` dataclass:

```python
@dataclass
class SearchResult:
    matches:     list[int]   # byte offsets (start for exact, end for fuzzy)
    duration_ms: float       # wall-clock time from the C timer
    algorithm:   str         # e.g. "Boyer-Moore", "KMP"
    total_count: int         # actual match count (may exceed len(matches) if truncated)
    truncated:   bool        # True if total_count > MAX_RESULTS (200 000)
```

Because ctypes releases the GIL during C function calls, multiple threads can run
`ThreadPoolExecutor` searches concurrently without serialisation.

---

## Heuristic Algorithm Selector

**File**: `app/processing/heuristics.py`

`select_algorithm()` examines a text sample (up to the first 64 KB) and the pattern,
then applies a deterministic decision tree — no ML, no training.

`profile_text()` computes:
- **Shannon entropy** (bits): low → monotone/repetitive text; high → natural language
- **Unique byte count**: < 20 → almost certainly binary or highly structured
- **Non-ASCII presence**: bytes ≥ 0x80 indicate UTF-8 multi-byte sequences (Hebrew, Arabic, CJK)
- **Top-byte frequency**: fraction held by the single most common byte

`explain_selection()` returns a human-readable string logged with every AUTO result
(stored in `algorithm_note` in the API response).

---

## Parallel & Streaming Search

**File**: `app/processing/parallel_search.py`

### ThreadedSearcher

Used for in-memory texts larger than 1 MB. Splits the byte array into chunks sized
`ceil(total / num_workers)`, with an `(pattern_len - 1)`-byte **overlap** appended to
each chunk. The overlap guarantees that a match straddling a chunk boundary is found
by exactly one worker. Duplicate matches at overlap boundaries are deduplicated before
the results are merged and sorted.

```
chunk₀ = text[0 : chunk_size + overlap]
chunk₁ = text[chunk_size : 2*chunk_size + overlap]
...
```

Each worker calls the appropriate C function through `wrapper.py`. Python threads
run concurrently because ctypes releases the GIL.

### StreamingSearcher

Used for files larger than `STREAMING_THRESHOLD` (50 MB). Reads the file in fixed
blocks (`BLOCK_SIZE` = 8 MB by default) sequentially, maintaining a `carry` buffer of
`pattern_len - 1` bytes from the previous block to bridge block boundaries. Matches are
emitted as absolute byte offsets from the start of the file.

### `search_large_file()`

Factory function that selects `StreamingSearcher` (file ≥ 50 MB) or `ThreadedSearcher`
(file < 50 MB loaded into RAM) automatically.

---

## Flask API

**Base URL**: `/api`

All responses follow the envelope format:
```json
{
  "status":  "success" | "error",
  "success": true | false,
  "message": "Human-readable string",
  "data":    { ... }
}
```

### Auth — `/api/auth`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/register` | None | Create account (username, email, password) |
| POST | `/login` | None | Returns JWT access token |
| GET | `/me` | JWT | Current user profile |
| PUT | `/change-password` | JWT | Update own password |

### Search — `/api/search`

| Method | Path | Auth | Description |
|---|---|---|---|
| POST | `/text` | JWT | Search plain text submitted as JSON |
| POST | `/file` | JWT | Upload a file (multipart) and search it |
| POST | `/multi` | JWT | Multi-pattern Aho-Corasick search |
| POST | `/compare` | JWT | Benchmark all four single-pattern algorithms in parallel |
| GET | `/autocomplete` | JWT | Prefix autocomplete from search history |
| GET | `/history` | JWT | Current user's search history (paginated) |

**`POST /text` request body**:
```json
{
  "text":       "...",
  "pattern":    "...",
  "algorithm":  "AUTO",
  "fuzzy":      false,
  "max_errors": 1,
  "enrich":     false
}
```

### Stats — `/api/stats`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/me` | JWT | Totals, algorithm breakdown, avg duration |
| GET | `/algorithms` | JWT | Per-algorithm avg timing, matches, text size |
| GET | `/trending` | JWT | Top-N queries across all users (rolling window) |
| GET | `/recommendations` | JWT | Rule-based personalised algorithm tips |

### Admin — `/api/admin`

| Method | Path | Auth | Description |
|---|---|---|---|
| GET | `/users` | Admin | List all users (paginated) |
| POST | `/users` | Admin | Create a user |
| GET | `/users/<id>` | Admin | Get single user |
| PUT | `/users/<id>` | Admin | Update user fields |
| DELETE | `/users/<id>` | Admin | Delete user |
| GET | `/search-history` | Admin | All search history records |
| GET | `/performance-logs` | Admin | All performance log records |

---

## Frontend Architecture

The frontend is server-rendered HTML (Jinja2) with Tailwind CSS (CDN) and vanilla
JavaScript. No build step is required.

### Styling

Tailwind CSS v3 CDN is loaded in `base.html`. CSS custom properties define the colour
theme on `:root`:

```css
--c-bg0:    #080812   /* deepest background */
--c-bg1:    #0d0d1a
--c-bg2:    #12122a
--c-bg3:    #1a1a35
--c-cyan:   #00d4ff   /* primary accent */
--c-purple: #8b5cf6   /* secondary accent */
```

### JavaScript modules

Each page loads its own JS file. All files share `api.js` which is included in `base.html`.

| File | Page | Responsibility |
|---|---|---|
| `api.js` | All | `API.get/post/put/del/postForm`, JWT storage, `showToast`, `escHtml`, `fmtMs`, `relTime` |
| `auth.js` | `/login` | Login / register tab switching, form submission |
| `dashboard.js` | `/dashboard` | Stat cards, algorithm bar chart, recommendations, trending chips, history table |
| `search.js` | `/search` | Autocomplete dropdown, file upload preview, algorithm picker, form submission |
| `results.js` | `/results` | Text highlighting with `<mark>`, match navigation, NER entity chips, compare bar chart |
| `admin.js` | `/admin` | User CRUD table, create/edit modal, delete confirmation |

### Authentication flow

1. `api.js` stores the JWT in `localStorage` under the key `apme_token`.
2. Every `API.get/post/…` call attaches `Authorization: Bearer <token>` automatically.
3. `API.requireAuth()` / `API.requireAdmin()` / `API.requireGuest()` redirect the browser
   to the appropriate page if the stored role does not match.
4. `API.user()` decodes the JWT payload (base64) client-side to extract `username`, `email`,
   and `role` without an extra round-trip.

### Inter-page data passing

Search results are serialised into `sessionStorage` as JSON under the key `apme_result`
by `search.js` and consumed by `results.js`. This avoids URL length limits for large
result sets.

Trending query prefill uses `sessionStorage.setItem('apme_prefill', query)` so that
clicking a trending chip on the dashboard pre-populates the search input.

---

## Data Flow

### Typical text search (AUTO algorithm)

```
Browser POST /api/search/text
    │
    ▼
search.py:search_text()
    │  extract user_id from JWT
    │
    ▼
APMESearchEngine.search(source, pattern, algorithm="AUTO")
    │
    ├─ profile_text(sample[:65536])       ← Shannon entropy, non-ASCII, monotone?
    ├─ select_algorithm(pat, sample, len) ← returns e.g. "Shift-Or"
    │
    ├─ file_size > 1 MB?
    │     yes → ThreadedSearcher.search(data, pat, alg)
    │            └─ ThreadPoolExecutor: N workers × apme_shift_or(chunk)
    │     no  → wrapper.search_shift_or(data, pat)
    │            └─ ctypes call → C: apme_shift_or() → results[]
    │
    ├─ enrich_ner=True? → enrich_match(text, pos, pat_len, context=120)
    │
    ├─ SearchHistoryModel.create(...)     ← MongoDB insert (best-effort)
    ├─ PerformanceLogModel.create(...)    ← MongoDB insert (best-effort)
    │
    └─ return dict → Flask jsonify → Browser
```

### File upload search

```
Browser POST /api/search/file (multipart)
    │
    ▼
search_file()
    ├─ validate extension (whitelist: .txt .log .csv .md .json .xml .html .py .js)
    ├─ save to tempfile.NamedTemporaryFile
    ├─ DocumentModel.create(file_name, path, size, user_id)
    │
    ▼
APMESearchEngine.search(tmp_path, pattern)
    ├─ is_file=True → file_size = os.path.getsize()
    ├─ file_size ≥ 50 MB → StreamingSearcher (block reads)
    │  file_size  < 50 MB → load into RAM → ThreadedSearcher or direct call
    │
    └─ return result dict
    │
    └─ os.unlink(tmp_path)   ← always deleted in finally block
```

---

## MongoDB Schema

### Collection: `users`

```json
{
  "_id":           ObjectId,
  "username":      "string",
  "email":         "string (unique)",
  "password_hash": "bcrypt string",
  "role":          "user | admin",
  "is_active":     true,
  "created_at":    ISODate
}
```

### Collection: `documents`

```json
{
  "_id":         ObjectId,
  "file_name":   "string",
  "file_path":   "string (temp path, deleted after search)",
  "size_bytes":  number,
  "uploaded_by": "user_id string",
  "uploaded_at": ISODate
}
```

### Collection: `search_history`

```json
{
  "_id":          ObjectId,
  "user_id":      "string",
  "query":        "string",
  "algorithm":    "KMP | Boyer-Moore | Rabin-Karp | Shift-Or | Aho-Corasick | FUZZY(k=N)",
  "files":        ["source label"],
  "matches_count": number,
  "duration_ms":  number,
  "run_at":       ISODate
}
```

Indexes: `user_id`, `run_at` (for time-window trending), `query` (for autocomplete prefix).

### Collection: `performance_logs`

```json
{
  "_id":            ObjectId,
  "algorithm":      "string",
  "file_path":      "string",
  "text_size_bytes": number,
  "duration_ms":    number,
  "matches_count":  number,
  "user_id":        "string",
  "logged_at":      ISODate
}
```

Used by `GET /api/stats/algorithms` and `GET /api/stats/recommendations` to report
per-algorithm average timing and identify faster alternatives.

---

## Authentication & Authorization

JWT tokens are issued at login via `flask_jwt_extended`. The token payload includes
`sub` (user_id), `role`, `username`, and `email`.

Two decorators in `app/utils/decorators.py` guard routes:

- `@login_required` — verifies a valid JWT is present. Any authenticated user passes.
- `@admin_required` — additionally checks `role == "admin"` in the JWT claims.

DB logging in `APMESearchEngine._log()` is **best-effort**: exceptions are silently
caught so a MongoDB outage never causes a search to fail.

---

## Algorithm Selection Table

| Condition | Algorithm selected |
|---|---|
| Multiple patterns requested | Aho-Corasick |
| Pattern contains bytes ≥ 0x80 (non-ASCII, e.g. Hebrew) | KMP |
| Pattern ≤ 4 bytes | KMP |
| Pattern ≤ 64 bytes AND ASCII-only AND text is NOT monotone | Shift-Or |
| Text Shannon entropy < 2.0 bits (monotone / repetitive) | KMP |
| Text is natural language (entropy > 4.5, >60 unique bytes) | Boyer-Moore |
| Text > 5 MB | Boyer-Moore |
| Default | Boyer-Moore |
| `fuzzy=true` | Wu-Manber Bitap (or Levenshtein DP if pattern > 64 bytes) |

---

## Deployment Notes

### Building the C library

```bash
cd c_engine
python build.py
# Produces: apme_engine.dll (Windows) or apme_engine.so (Linux/macOS)
```

The library path is resolved at runtime by `app/engine/loader.py`. It searches:
1. The `c_engine/` directory relative to the project root.
2. The system library path (`LD_LIBRARY_PATH` / `PATH`).

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `MONGO_URI` | `mongodb://localhost:27017/` | MongoDB connection string |
| `MONGO_DB_NAME` | `apme_db` | Database name |
| `JWT_SECRET_KEY` | (required) | HS256 signing key for JWT |
| `JWT_ACCESS_TOKEN_EXPIRES` | `3600` | Token lifetime in seconds |
| `FLASK_ENV` | `production` | `development` enables auto-reload and debug |

### Running

```bash
pip install -r requirements.txt
python run.py          # development server (port 5000)
```

For production, run behind a WSGI server (Gunicorn, uWSGI) with `app` as the callable:

```bash
gunicorn "app:create_app()" -w 4 -b 0.0.0.0:5000
```

Use `--preload` with Gunicorn so the C library is loaded once in the master process
and inherited by all workers without re-linking.
