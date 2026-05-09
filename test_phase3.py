"""
Phase 3 smoke-tests:
  1. Heuristic selection across various input profiles
  2. Parallel / threaded search on a generated large text
  3. NER entity extraction (dates, emails, phones, names, IDs)
  4. File monitor (write to a temp file, watch for matches)
  5. APMESearchEngine orchestrator (text + file)
"""

import os
import sys
import time
import tempfile
import threading

sys.path.insert(0, os.path.dirname(__file__))

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"


def chk(label: str, condition: bool):
    print(f"  [{PASS if condition else FAIL}] {label}")
    return condition


# ─────────────────────────────────────────────────────────────
# 1. Heuristics
# ─────────────────────────────────────────────────────────────
def test_heuristics():
    print("\n=== 1. Heuristic Selection ===")
    from app.processing.heuristics import select_algorithm, profile_text
    ok = True

    # Multi-pattern -> Aho-Corasick
    alg = select_algorithm([b"cat", b"dog"], multi_pattern=True)
    ok &= chk(f"multi-pattern -> Aho-Corasick (got {alg})", alg == "Aho-Corasick")

    # Short ASCII pattern (<=64B, varied text) -> Shift-Or
    varied = bytes(range(256)) * 100
    alg = select_algorithm(b"hello", text_sample=varied, text_len=len(varied))
    ok &= chk(f"short ASCII, varied text -> Shift-Or (got {alg})", alg == "Shift-Or")

    # Non-ASCII pattern (Hebrew) -> KMP
    alg = select_algorithm("שלום".encode("utf-8"))
    ok &= chk(f"Hebrew pattern -> KMP (got {alg})", alg == "KMP")

    # Monotone text -> KMP
    mono = b"a" * 100_000
    alg = select_algorithm(b"aaaa", text_sample=mono, text_len=len(mono))
    ok &= chk(f"monotone text -> KMP (got {alg})", alg == "KMP")

    # Long ASCII pattern, natural text -> Boyer-Moore
    natural = b"The quick brown fox jumps over the lazy dog. " * 3000
    alg = select_algorithm(b"x" * 65, text_sample=natural, text_len=len(natural))
    ok &= chk(f"long ASCII, natural text -> BM (got {alg})", alg == "Boyer-Moore")

    return ok


# ─────────────────────────────────────────────────────────────
# 2. Parallel search
# ─────────────────────────────────────────────────────────────
def test_parallel():
    print("\n=== 2. Parallel / Threaded Search ===")
    from app.processing.parallel_search import ThreadedSearcher

    # Build a 6 MB text with known pattern placements
    base    = b"the quick brown fox jumps over the lazy dog. "
    filler  = base * (6 * 1024 * 1024 // len(base) + 1)
    MARKER  = b"NEEDLE_PATTERN_XYZ"
    # Insert markers at positions 0, 1 MB, 3 MB, 5 MB
    positions = [0, 1_000_000, 3_000_000, 5_000_000]
    data = bytearray(filler[:6_000_000])
    for p in positions:
        data[p : p + len(MARKER)] = MARKER

    searcher = ThreadedSearcher(max_workers=4, chunk_size=2_000_000)
    result   = searcher.search(bytes(data), MARKER, algorithm="Boyer-Moore")

    ok = True
    ok &= chk(f"found all 4 markers (got {len(result.matches)})", len(result.matches) == 4)
    ok &= chk("all expected positions present",
              all(p in result.matches for p in positions))
    ok &= chk("result sorted", result.matches == sorted(result.matches))
    print(f"  duration={result.duration_ms:.2f}ms  chunks={result.chunks_used}")
    return ok


# ─────────────────────────────────────────────────────────────
# 3. NER
# ─────────────────────────────────────────────────────────────
def test_ner():
    print("\n=== 3. Named Entity Recognition ===")
    from app.processing.ner import extract_entities

    sample = (
        "Meeting on 2024-05-15 at 14:30 with John Smith. "
        "Contact: john.smith@example.com or +972-52-123-4567. "
        "Server IP is 192.168.1.100. See https://www.example.com. "
        "ID number 012345678. #techmeeting @jsmith. "
        "נועה כהן ביקרה ב-01/06/2024."
    )

    entities = extract_entities(sample)
    types_found = {e.type for e in entities}
    ok = True

    for etype in ("DATE", "TIME", "EMAIL", "PHONE", "IP_ADDRESS", "URL",
                  "HASHTAG", "MENTION", "ENGLISH_NAME"):
        found = etype in types_found
        ok &= chk(f"entity type {etype} detected", found)

    # Print all found entities
    for e in entities:
        print(f"    {e.type:15s}  '{e.value}'")
    return ok


# ─────────────────────────────────────────────────────────────
# 4. File monitor
# ─────────────────────────────────────────────────────────────
def test_monitor():
    print("\n=== 4. File Monitor ===")
    from app.processing.monitor import FileMonitor

    from app.processing.monitor import MonitorEvent
    received: list[MonitorEvent] = []
    event_flag = threading.Event()

    def callback(evt: MonitorEvent):
        received.append(evt)
        event_flag.set()

    monitor = FileMonitor()

    with tempfile.NamedTemporaryFile(suffix=".log", delete=False, mode="wb") as f:
        tmp_path = f.name
        f.write(b"initial line\n")

    try:
        watch_id = monitor.watch(tmp_path, b"ERROR", callback, algorithm="KMP")
        time.sleep(0.5)   # let observer settle

        # Append a line with the trigger word
        with open(tmp_path, "ab") as f:
            f.write(b"2024-01-01 12:00 ERROR: disk full\n")

        triggered = event_flag.wait(timeout=5)
        ok = True
        ok &= chk("monitor callback triggered within 5s", triggered)
        if triggered:
            ok &= chk("new match detected",
                      any(evt.matches for evt in received))
        monitor.stop(watch_id)
    finally:
        os.unlink(tmp_path)

    return ok


# ─────────────────────────────────────────────────────────────
# 5. Orchestrator
# ─────────────────────────────────────────────────────────────
def test_orchestrator():
    print("\n=== 5. APMESearchEngine Orchestrator ===")
    from app.search_engine import APMESearchEngine

    engine = APMESearchEngine(enable_db=False, parallel=True, enrich_ner=True)
    ok = True

    # Text search (AUTO)
    text = "the cat sat on the mat, the cat ate the rat"
    r = engine.search(text, "cat", algorithm="AUTO")
    ok &= chk(f"text search: found {r['match_count']} matches", r["match_count"] == 2)
    ok &= chk("algorithm selected", bool(r.get("algorithm")))
    ok &= chk("NER enriched", "enriched" in r)

    # Hebrew text
    he_text = "שלום עולם. שלום לכולם. שלום שלום."
    r_he = engine.search(he_text.encode("utf-8"), "שלום".encode("utf-8"),
                         algorithm="AUTO")
    ok &= chk(f"Hebrew search: found {r_he['match_count']} (expect 4)", r_he["match_count"] == 4)

    # File search
    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False, mode="wb") as f:
        tmp = f.name
        f.write((text * 1000).encode())
    try:
        r_file = engine.search(tmp, "rat", algorithm="AUTO")
        ok &= chk(f"file search: found {r_file['match_count']} matches",
                  r_file["match_count"] == 1000)
    finally:
        os.unlink(tmp)

    # Multi-pattern
    mp = engine.search_multi(text, ["cat", "rat", "mat"])
    ok &= chk("multi-pattern: cat found", mp["results"]["cat"]["match_count"] == 2)
    ok &= chk("multi-pattern: rat found", mp["results"]["rat"]["match_count"] == 1)

    # Fuzzy
    r_fz = engine.search(text, "cot", fuzzy=True, max_errors=1)  # "cot" is 1 sub from "cat"
    ok &= chk(f"fuzzy search triggered", r_fz["match_count"] > 0)

    return ok


# ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    results = [
        test_heuristics(),
        test_parallel(),
        test_ner(),
        test_monitor(),
        test_orchestrator(),
    ]
    print("\n" + ("=" * 50))
    if all(results):
        print("ALL PHASE 3 TESTS PASSED")
        sys.exit(0)
    else:
        print(f"FAILURES: {results.count(False)} / {len(results)} suites")
        sys.exit(1)
