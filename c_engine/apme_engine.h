/*
 * APME Search Engine — Public C API
 * All text and pattern arguments are raw byte buffers (UTF-8 safe).
 * All returned indices are byte offsets from the start of the text.
 *
 * Return value of every search function:
 *   >= 0  : total number of matches found (results[] is filled up to max_results)
 *   -1    : memory allocation failure
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

/* ── Single-pattern algorithms ──────────────────────────────────────────── */

APME_EXPORT int apme_kmp(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

APME_EXPORT int apme_boyer_moore(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

APME_EXPORT int apme_rabin_karp(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

/* Shift-Or / Bitap — fastest for short patterns (pattern_len <= 64 bytes).
   Falls back to KMP automatically for longer patterns. */
APME_EXPORT int apme_shift_or(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms
);

/* ── Multi-pattern: Aho-Corasick ─────────────────────────────────────── */

/* patterns     : array of byte-buffer pointers (num_patterns entries)
   pat_lengths  : byte length of each pattern
   pattern_ids  : on return, pattern_ids[i] holds which pattern matched at results[i] */
APME_EXPORT int apme_aho_corasick(
    const char* text, int text_len,
    const char** patterns, const int* pat_lengths, int num_patterns,
    int* results, int* pattern_ids, int max_results,
    double* duration_ms
);

/* ── Approximate / fuzzy matching ────────────────────────────────────── */

/* max_errors: maximum allowed edit distance (insertions + deletions + substitutions).
   Each entry in results[] is the END byte offset of an approximate match window.
   Use max_errors = 0 for exact match via bitap. */
APME_EXPORT int apme_fuzzy(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int max_errors,
    int* results, int max_results,
    double* duration_ms
);

/* ── Library info ────────────────────────────────────────────────────── */
APME_EXPORT const char* apme_version(void);

#ifdef __cplusplus
}
#endif
#endif /* APME_ENGINE_H */
