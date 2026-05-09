"""
Quick smoke-test for all C algorithms.
Run: python test_engine.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.engine.wrapper import (
    search_kmp, search_boyer_moore, search_rabin_karp,
    search_shift_or, search_aho_corasick, search_fuzzy,
    engine_version,
)

TEXT_EN = "the cat sat on the mat, the cat ate the rat"
TEXT_HE = "שלום עולם, זהו מנוע חיפוש טקסט. שלום לכולם"
PAT_EN  = "cat"
PAT_HE  = "שלום"


def check(label, result, expected_positions):
    ok = sorted(result.matches) == sorted(expected_positions)
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {label:30s}  matches={result.matches}  "
          f"time={result.duration_ms:.4f}ms")
    return ok


def main():
    print(f"Library: {engine_version()}\n")
    all_ok = True

    # --- English exact match
    kmp_en   = search_kmp(TEXT_EN, PAT_EN)
    bm_en    = search_boyer_moore(TEXT_EN, PAT_EN)
    rk_en    = search_rabin_karp(TEXT_EN, PAT_EN)
    so_en    = search_shift_or(TEXT_EN, PAT_EN)

    # "cat" appears at bytes 4 and 28
    # "the cat sat on the mat, the cat ate the rat"
    #       ^4                      ^28
    expected = [4, 28]
    print("=== English exact match ('cat') ===")
    for label, r in [("KMP", kmp_en), ("Boyer-Moore", bm_en),
                     ("Rabin-Karp", rk_en), ("Shift-Or", so_en)]:
        all_ok &= check(label, r, expected)

    # --- Hebrew exact match
    pat_b = PAT_HE.encode("utf-8")
    txt_b = TEXT_HE.encode("utf-8")
    kmp_he = search_kmp(txt_b, pat_b)
    bm_he  = search_boyer_moore(txt_b, pat_b)

    # שלום starts at byte 0 and byte 34 (after the comma region)
    exp_he = [TEXT_HE.encode().index(pat_b)]
    # find second occurrence
    second = TEXT_HE.encode().index(pat_b, exp_he[0] + 1)
    exp_he.append(second)

    print("\n=== Hebrew exact match ('שלום') ===")
    for label, r in [("KMP", kmp_he), ("Boyer-Moore", bm_he)]:
        all_ok &= check(label, r, exp_he)

    # --- Aho-Corasick multi-pattern
    print("\n=== Aho-Corasick multi-pattern ===")
    ac = search_aho_corasick(TEXT_EN, ["cat", "rat", "mat"])
    for pat, r in ac.items():
        print(f"  pattern='{pat}'  matches={r.matches}  time={r.duration_ms:.4f}ms")

    # --- Fuzzy
    print("\n=== Fuzzy (k=1 error) ===")
    fz = search_fuzzy(TEXT_EN, "cot", max_errors=1)  # should match 'cat'
    print(f"  'cot' ~1 in '{TEXT_EN}'")
    print(f"  matches(end offsets)={fz.matches}  time={fz.duration_ms:.4f}ms")

    print("\n" + ("ALL TESTS PASSED" if all_ok else "SOME TESTS FAILED"))
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
