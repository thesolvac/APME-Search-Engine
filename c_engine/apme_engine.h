/*
 * ============================================================================
 * APME Search Engine — Public C API                          apme_engine.h
 * ============================================================================
 *
 * OVERVIEW
 * --------
 * Six string-matching algorithms compiled into a single shared library
 * (apme_engine.dll / apme_engine.so).  All functions operate on raw byte
 * buffers, making them UTF-8 safe: a multi-byte UTF-8 sequence is treated as
 * a run of bytes, so pattern matches always land on valid code-point
 * boundaries (UTF-8 self-synchronising property).
 *
 * RETURN VALUE (all search functions)
 * ------------------------------------
 *   >= 0  total number of matches found.
 *          results[] is filled with up to max_results byte offsets.
 *          If the actual count exceeds max_results the array is filled to
 *          capacity and the surplus is counted but not stored (truncated).
 *   -1    memory allocation failure inside the C library.
 *
 * ALL INDICES are byte offsets from the start of the text buffer.
 * For fuzzy search, each index is the END byte offset of the approximate
 * match window (not the start).
 *
 * TIMING
 * ------
 * Every function writes the wall-clock elapsed time in milliseconds into
 * *duration_ms.  Timing uses QueryPerformanceCounter on Windows and
 * clock_gettime(CLOCK_MONOTONIC) on POSIX systems.
 *
 * ============================================================================
 */

#ifndef APME_ENGINE_H
#define APME_ENGINE_H

#include <stdint.h>

#ifdef _WIN32
#  define APME_EXPORT __declspec(dllexport)
#else
#  define APME_EXPORT __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif


/* ── Single-pattern algorithms ───────────────────────────────────────────────
 *
 * All four functions below share the same signature:
 *
 *   text        : pointer to the text buffer (not NUL-terminated)
 *   text_len    : length of the text in bytes
 *   pattern     : pointer to the pattern buffer (not NUL-terminated)
 *   pattern_len : length of the pattern in bytes
 *   results     : caller-allocated output array of byte offsets (capacity max_results)
 *   max_results : maximum entries to write into results[]
 *   duration_ms : output — elapsed wall-clock time in milliseconds
 */

/*
 * apme_kmp — Knuth-Morris-Pratt
 * ─────────────────────────────
 * Algorithm:
 *   1. Preprocessing (O(m)): Build the "failure function" (LPS — Longest
 *      Proper Prefix which is also a Suffix) array from the pattern.
 *      lps[i] = length of the longest proper prefix of pattern[0..i] that is
 *      also a suffix.  This encodes the shift distance after a mismatch.
 *   2. Scanning (O(n)): A single left-to-right pass over the text.  On
 *      mismatch at text[i] vs pattern[j], the pointer j falls back to
 *      lps[j-1] without retreating i.
 *
 * Complexity: O(n + m) time, O(m) space.
 * Best for : non-ASCII / multi-byte patterns (Hebrew, Arabic, CJK) where
 *            Boyer-Moore's skip tables degenerate; very short patterns
 *            (m ≤ 4 bytes); highly repetitive (monotone) text.
 */
APME_EXPORT int apme_kmp(
    const char* text,    int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

/*
 * apme_boyer_moore — Boyer-Moore with bad-character and good-suffix heuristics
 * ─────────────────────────────────────────────────────────────────────────────
 * Algorithm:
 *   1. Bad-character table (O(sigma + m)): For each byte value b, store the
 *      rightmost position of b in the pattern.  On mismatch at text[i] and
 *      pattern[j], shift pattern right by max(1, j - bc[text[i]]).
 *   2. Good-suffix table (O(m)): After a mismatch at position j, shift by
 *      the distance to the nearest occurrence of pattern[j+1..m-1] in the
 *      pattern that is preceded by a different character (or by a prefix of
 *      the pattern that matches a suffix of pattern[j+1..m-1]).
 *   3. Scanning: Right-to-left character comparison within the pattern window,
 *      left-to-right window advancement.  The combined heuristics yield
 *      sub-linear average behaviour on natural text.
 *
 * Complexity: O(n·m) worst-case (rarely reached), O(n/m) best-case average
 *             on random text.  O(m + sigma) space.
 * Best for : large ASCII corpora with medium-to-long patterns (m > 64 bytes);
 *            natural-language text (high character entropy).
 */
APME_EXPORT int apme_boyer_moore(
    const char* text,    int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

/*
 * apme_rabin_karp — Rabin-Karp with double rolling polynomial hash
 * ────────────────────────────────────────────────────────────────
 * Algorithm:
 *   Maintain two independent polynomial rolling hashes over a sliding window
 *   of length m through the text.  On each step, subtract the outgoing byte's
 *   contribution, shift by the base, and add the incoming byte.
 *
 *   Double hash eliminates spurious collisions: a position is verified only
 *   when both hash values match the pattern hashes.  If both match, a
 *   byte-by-byte confirmation pass is still performed (O(m)) to guarantee
 *   correctness.
 *
 *   Parameters used:
 *     Hash 1: base=257,  modulus=1 000 000 007  (large prime)
 *     Hash 2: base=131,  modulus=998 244 353     (NTT-friendly prime)
 *
 * Complexity: O(n + m) average, O(n·m) worst-case (hash collisions).
 *             O(1) space (excluding output buffer).
 * Best for : verification-heavy pipelines; multiple pattern queries against
 *            the same text (hash can be reused); educational / reference path.
 */
APME_EXPORT int apme_rabin_karp(
    const char* text,    int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

/*
 * apme_shift_or — Shift-Or (Bitap / Wu-Manber exact variant)
 * ──────────────────────────────────────────────────────────
 * Algorithm:
 *   Represent the NFA for "pattern occurred" as a 64-bit integer (one bit
 *   per pattern position).  For each text byte t:
 *     state = (state << 1) | D[t]
 *   where D[c] is a bitmask with bit i set iff pattern[i] != c.
 *   A match is detected when bit (m-1) of state is 0.
 *
 *   Bit-level parallelism lets a single CPU instruction process all m pattern
 *   positions simultaneously, giving a constant-time inner loop regardless of
 *   pattern length (up to 64 bytes).
 *
 *   Automatic fallback: patterns longer than 64 bytes are redirected to KMP.
 *
 * Complexity: O(n · ⌈m/w⌉) where w = 64 (word size).  For m ≤ 64: O(n).
 *             O(sigma) space for D[] table.
 * Best for : short ASCII patterns (m ≤ 64 bytes) in varied text; situations
 *            where branch misprediction cost of character comparison dominates.
 */
APME_EXPORT int apme_shift_or(
    const char* text,    int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);


/* ── Multi-pattern: Aho-Corasick ─────────────────────────────────────────────
 *
 * apme_aho_corasick — Aho-Corasick automaton
 * ───────────────────────────────────────────
 * Algorithm:
 *   1. Trie construction (O(sum(m_i))): Insert all patterns into a trie of
 *      AcNode structs (index-based, 256 children each).
 *   2. Failure-link BFS (O(sum(m_i))): For each trie node, compute the
 *      "failure link" (longest proper suffix of the current path that is also
 *      a prefix of some pattern) using a breadth-first traversal.
 *      "Output links" chain nodes whose failure-link paths pass through a
 *      pattern endpoint, enabling detection of overlapping matches.
 *   3. Scanning (O(n + k)): A single left-to-right pass over the text.
 *      On each byte: follow the child edge if it exists, otherwise follow
 *      failure links until a match or the root is reached.  Emit matches
 *      along output-link chains.
 *
 * Memory: O(SIGMA * |trie|) where SIGMA=256.  AC_MAX_NODES=131 072 limits
 *         trie size (~128 K × 256 × 4B ≈ 128 MB worst-case); returns -1 if
 *         this limit is exceeded.
 *
 * Complexity: O(n + sum(m_i) + k) time where k = total match count.
 * Best for : searching for tens to thousands of patterns simultaneously;
 *            log scanning for known attack signatures; keyword filtering.
 *
 * Parameters:
 *   patterns     : array of num_patterns byte-buffer pointers
 *   pat_lengths  : byte length of each pattern in patterns[]
 *   num_patterns : number of patterns
 *   results      : output byte offsets of match starts (capacity max_results)
 *   pattern_ids  : output parallel array: pattern_ids[i] = index of the
 *                  pattern that matched at results[i]
 */
APME_EXPORT int apme_aho_corasick(
    const char*  text,        int text_len,
    const char** patterns,    const int* pat_lengths, int num_patterns,
    int*         results,     int* pattern_ids,       int max_results,
    double*      duration_ms
);


/* ── Approximate / fuzzy matching ────────────────────────────────────────────
 *
 * apme_fuzzy — Wu-Manber k-error Bitap with Levenshtein DP fallback
 * ──────────────────────────────────────────────────────────────────
 * Algorithm (primary — patterns ≤ 64 bytes):
 *   Extend Shift-Or to the k-error case using k+1 bit-vectors R[0..k].
 *   R[d] tracks positions in the text where the pattern matches with exactly
 *   d edit operations (insertions, deletions, substitutions).
 *
 *   Recurrence for each text byte t:
 *     R'[0] = (R[0] << 1) | D[t]                    (exact)
 *     R'[d] = (R[d] << 1 | D[t]) & (R[d-1] << 1)   (substitution)
 *                                 & (R'[d-1])         (insertion)
 *                                 & (R[d-1])          (deletion)
 *
 *   A match with ≤ k errors is detected when bit (m-1) of R[k] is 0.
 *   Each entry in results[] is the END byte offset of the matching window.
 *
 * Algorithm (fallback — patterns > 64 bytes):
 *   Classical O(n·m) Levenshtein DP over a sliding text window.  The DP row
 *   is initialised to [0, 1, 2, …, m] so that partial prefixes of the text
 *   can match anywhere (global text position is free, pattern alignment is
 *   fixed).  A match is recorded whenever the last cell ≤ max_errors.
 *
 * Parameters:
 *   max_errors   : maximum edit distance (0 = exact match via bitap)
 *   results      : END byte offsets of approximate match windows
 *
 * Complexity: O(n · k) primary; O(n · m) fallback.  O(k) / O(m) space.
 * Best for : typo-tolerant search; OCR post-correction; log entries with
 *            field-value noise.
 */
APME_EXPORT int apme_fuzzy(
    const char* text,    int text_len,
    const char* pattern, int pattern_len,
    int         max_errors,
    int*        results, int max_results,
    double*     duration_ms
);


/* ── Library info ─────────────────────────────────────────────────────────────
 *
 * apme_version — return a static NUL-terminated version string.
 * Example return value: "APME-Engine 2.0.0"
 * The returned pointer is valid for the lifetime of the process.
 */
APME_EXPORT const char* apme_version(void);


#ifdef __cplusplus
}
#endif
#endif /* APME_ENGINE_H */
