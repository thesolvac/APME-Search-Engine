# APME Search Engine

Adaptive Pattern Matching Engine — a full-stack text search system built around a compiled
C shared library that exposes **six string-matching algorithms** through a Flask REST API
and a dark-themed web UI.

## Algorithms

All six algorithms are implemented in native C (`c_engine/apme_engine.c`), wrapped in
Python via `ctypes`, selectable from the web UI, and benchmarked side-by-side in the
comparison view.

| # | Algorithm | UI label | Best for | Time complexity |
|---|-----------|----------|----------|-----------------|
| 1 | **Knuth-Morris-Pratt** | `KMP` | Non-ASCII / Hebrew / Arabic patterns; very short patterns (≤ 4 bytes); highly repetitive text | O(n + m) |
| 2 | **Boyer-Moore** (bad-character + good-suffix) | `Boyer-Moore` | Long ASCII patterns in natural-language text; large corpora | O(n/m) avg, O(nm) worst |
| 3 | **Rabin-Karp** double rolling hash | `Rabin-Karp` | Verification-heavy pipelines; multiple queries against the same text | O(n + m) avg |
| 4 | **Shift-Or / Bitap** (64-bit NFA) | `Shift-Or` | Short ASCII patterns ≤ 64 bytes; branch-misprediction-sensitive paths | O(n) for m ≤ 64 |
| 5 | **Aho-Corasick** trie + BFS failure links | `Aho-Corasick` | Simultaneous multi-pattern search; log scanning; keyword filtering | O(n + Σm + k) |
| 6 | **Wu-Manber k-error Bitap** + Levenshtein DP fallback | `Fuzzy` | Typo-tolerant search; OCR post-correction; approximate matching | O(n·k) primary |

> **n** = text length · **m** = pattern length · **k** = error budget / match count · **Σm** = sum of all pattern lengths

### Algorithm notes

- **Shift-Or** automatically falls back to KMP for patterns longer than 64 bytes.
- **Fuzzy** uses Wu-Manber k-error Bitap for patterns ≤ 64 bytes and Levenshtein DP for longer patterns.
  The error budget (edit distance) is configurable via the **Max edit distance** control (0–5).
- **Aho-Corasick** is the only multi-pattern algorithm. In the main search interface it accepts a single
  pattern; in **Multi-Pattern** mode it searches for all patterns simultaneously in one pass.
- **AUTO** mode lets the heuristic engine pick the best algorithm automatically based on pattern length,
  character set (ASCII vs. non-ASCII), Shannon entropy of the text, and total text size.

---

## Project Structure

```
APME-Search-Engine/
├── c_engine/            # Native C library (compile with build.py)
│   ├── apme_engine.h    # Public API — all six function declarations
│   └── apme_engine.c    # Implementations
├── app/
│   ├── engine/          # ctypes loader + Python wrapper
│   ├── processing/      # Heuristics, parallel/streaming search, NER, file monitor
│   ├── models/          # MongoDB collections (users, documents, history, perf logs)
│   ├── routes/          # Flask blueprints (auth, search, stats, admin, views)
│   ├── static/          # JS (api, auth, search, results, dashboard, admin) + CSS
│   └── templates/       # Jinja2 HTML pages
├── tests/               # Unit + integration tests
├── ARCHITECTURE.md      # Full system architecture document
├── config.py
└── run.py
```

---

## Quick Start

### 1. Build the C library

```bash
cd c_engine
python build.py
# → apme_engine.dll (Windows) or apme_engine.so (Linux/macOS)
```

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
# Required
export JWT_SECRET_KEY="change-me-in-production"

# Optional (defaults shown)
export MONGO_URI="mongodb://localhost:27017/"
export MONGO_DB_NAME="apme_db"
export FLASK_ENV="development"
```

### 4. Run

```bash
python run.py
# → http://localhost:5000
```

---

## Web UI Pages

| Path | Description |
|------|-------------|
| `/` | Landing page |
| `/login` | Login / Register |
| `/search` | Main search interface — all 6 algorithm pills, multi-pattern mode, file upload |
| `/results` | Results viewer — highlighted text, NER entities, 6-algorithm comparison chart |
| `/dashboard` | Personal statistics, trending queries, algorithm breakdown, recommendations |
| `/admin` | User management (admin only) |

---

## API Overview

All endpoints return `{"status":"success"|"error", "success":bool, "message":"...", "data":{...}}`.

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Create account |
| POST | `/api/auth/login` | Obtain JWT token |
| POST | `/api/search/text` | Search plain text (all 6 algorithms) |
| POST | `/api/search/file` | Upload + search a file |
| POST | `/api/search/multi` | Multi-pattern Aho-Corasick search |
| POST | `/api/search/compare` | Benchmark all 6 algorithms in parallel |
| GET | `/api/search/autocomplete` | Prefix autocomplete |
| GET | `/api/search/history` | Current user's search history |
| GET | `/api/stats/me` | Personal usage statistics |
| GET | `/api/stats/recommendations` | Rule-based algorithm recommendations |
| GET | `/api/stats/trending` | Globally trending queries |

Full details in [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Tech Stack

- **C** — six search algorithms compiled to a shared library
- **Python / Flask** — REST API, JWT authentication, heuristic algorithm selector
- **ctypes** — zero-copy Python ↔ C bridge (GIL released during C calls)
- **MongoDB** — search history, performance logs, user accounts
- **Tailwind CSS CDN + Vanilla JS** — no build step required
