/*
 * APME Search Engine — Core C Implementation
 *
 * Algorithms:
 *   1. KMP          — guaranteed O(n+m), ideal for repetitive/monotone text
 *   2. Boyer-Moore  — sub-linear average for natural text; bad-char + good-suffix
 *   3. Rabin-Karp   — double-hash rolling window; best for multi-pattern pre-filter
 *   4. Shift-Or     — bitap, bit-parallel, fastest for short patterns (<=64 B)
 *   5. Aho-Corasick — simultaneous multi-pattern search in O(n + total_m + matches)
 *   6. Fuzzy/Bitap  — k-mismatches via Wu-Manber; DP fallback for long patterns
 *
 * UTF-8 notes:
 *   All algorithms operate on raw bytes.  Because UTF-8 is self-synchronising
 *   (continuation bytes are always 10xxxxxx, i.e. 0x80-0xBF, which never appear
 *   as leading bytes), a byte-level match of a valid UTF-8 pattern inside a valid
 *   UTF-8 text will always land on a character boundary.  Returned indices are
 *   byte offsets from the start of the text buffer.
 *
 * Memory:
 *   Every function allocates and frees its own internal buffers.
 *   The caller owns results[] and must ensure it is large enough (max_results).
 */

#include "apme_engine.h"

#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <limits.h>

#ifdef _WIN32
#  include <windows.h>
#else
#  include <time.h>
#endif

/* =========================================================================
   Timing
   ========================================================================= */

static double now_ms(void) {
#ifdef _WIN32
    LARGE_INTEGER freq, cnt;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&cnt);
    return (double)cnt.QuadPart / (double)freq.QuadPart * 1000.0;
#else
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
#endif
}

/* =========================================================================
   Version
   ========================================================================= */

APME_EXPORT const char* apme_version(void) {
    return "APME-Engine 2.0.0";
}

/* =========================================================================
   1.  KMP — Knuth-Morris-Pratt
   ========================================================================= */

static void kmp_build_lps(const unsigned char* p, int m, int* lps) {
    lps[0] = 0;
    int len = 0, i = 1;
    while (i < m) {
        if (p[i] == p[len]) {
            lps[i++] = ++len;
        } else if (len) {
            len = lps[len - 1];
        } else {
            lps[i++] = 0;
        }
    }
}

APME_EXPORT int apme_kmp(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();
    int count = 0;

    if (!text || !pattern || pattern_len <= 0 || text_len < pattern_len) {
        *duration_ms = now_ms() - t0;
        return 0;
    }

    const unsigned char* t = (const unsigned char*)text;
    const unsigned char* p = (const unsigned char*)pattern;

    int* lps = (int*)malloc((size_t)pattern_len * sizeof(int));
    if (!lps) { *duration_ms = 0; return -1; }

    kmp_build_lps(p, pattern_len, lps);

    int i = 0, j = 0;
    while (i < text_len) {
        if (t[i] == p[j]) { i++; j++; }

        if (j == pattern_len) {
            if (count < max_results)
                results[count] = i - j;
            count++;
            j = lps[j - 1];
        } else if (i < text_len && t[i] != p[j]) {
            if (j) j = lps[j - 1];
            else   i++;
        }
    }

    free(lps);
    *duration_ms = now_ms() - t0;
    return count;
}

/* =========================================================================
   2.  Boyer-Moore (Bad Character + Good Suffix)
   ========================================================================= */

/* --- bad character table ------------------------------------------------ */
static void bm_bad_char(const unsigned char* p, int m, int bc[256]) {
    for (int i = 0; i < 256; i++) bc[i] = -1;
    for (int i = 0; i < m;   i++) bc[(int)p[i]] = i;
}

/* --- good suffix tables ------------------------------------------------- */
static void bm_good_suffix(const unsigned char* p, int m, int* shift, int* border) {
    /* Phase 1: compute border positions */
    int i = m, j = m + 1;
    border[i] = j;
    while (i > 0) {
        while (j <= m && p[i - 1] != p[j - 1]) {
            if (shift[j] == 0)
                shift[j] = j - i;
            j = border[j];
        }
        border[--i] = --j;
    }
    /* Phase 2: fill remaining shift entries using whole-pattern borders */
    j = border[0];
    for (i = 0; i <= m; i++) {
        if (shift[i] == 0)
            shift[i] = j;
        if (i == j)
            j = border[j];
    }
}

APME_EXPORT int apme_boyer_moore(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();
    int count = 0;

    if (!text || !pattern || pattern_len <= 0 || text_len < pattern_len) {
        *duration_ms = now_ms() - t0;
        return 0;
    }

    const unsigned char* t = (const unsigned char*)text;
    const unsigned char* p = (const unsigned char*)pattern;
    int n = text_len, m = pattern_len;

    int bc[256];
    bm_bad_char(p, m, bc);

    /* shift[] and border[] each need m+1 ints */
    int* shift  = (int*)calloc((size_t)(m + 1), sizeof(int));
    int* border = (int*)malloc((size_t)(m + 1) * sizeof(int));
    if (!shift || !border) {
        free(shift); free(border);
        *duration_ms = 0;
        return -1;
    }
    bm_good_suffix(p, m, shift, border);
    free(border);   /* no longer needed */

    int s = 0;  /* shift of the pattern relative to text */
    while (s <= n - m) {
        int j = m - 1;
        /* match from right to left */
        while (j >= 0 && p[j] == t[s + j]) j--;

        if (j < 0) {
            /* full match */
            if (count < max_results)
                results[count] = s;
            count++;
            s += shift[0];
        } else {
            int bad  = j - bc[(int)t[s + j]];
            int good = shift[j + 1];
            s += (bad > good) ? bad : good;
        }
    }

    free(shift);
    *duration_ms = now_ms() - t0;
    return count;
}

/* =========================================================================
   3.  Rabin-Karp (double rolling hash)
   ========================================================================= */

#define RK_BASE1 257ULL
#define RK_MOD1  1000000007ULL
#define RK_BASE2 131ULL
#define RK_MOD2  998244353ULL

APME_EXPORT int apme_rabin_karp(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();
    int count = 0;

    if (!text || !pattern || pattern_len <= 0 || text_len < pattern_len) {
        *duration_ms = now_ms() - t0;
        return 0;
    }

    const unsigned char* t = (const unsigned char*)text;
    const unsigned char* p = (const unsigned char*)pattern;
    int n = text_len, m = pattern_len;

    /* Precompute pattern hashes and the m-th power of bases */
    uint64_t ph1 = 0, ph2 = 0;
    uint64_t pow1 = 1, pow2 = 1;

    for (int i = 0; i < m; i++) {
        ph1 = (ph1 * RK_BASE1 + p[i]) % RK_MOD1;
        ph2 = (ph2 * RK_BASE2 + p[i]) % RK_MOD2;
        if (i < m - 1) {
            pow1 = (pow1 * RK_BASE1) % RK_MOD1;
            pow2 = (pow2 * RK_BASE2) % RK_MOD2;
        }
    }

    /* Compute hash of first window */
    uint64_t th1 = 0, th2 = 0;
    for (int i = 0; i < m; i++) {
        th1 = (th1 * RK_BASE1 + t[i]) % RK_MOD1;
        th2 = (th2 * RK_BASE2 + t[i]) % RK_MOD2;
    }

    for (int i = 0; i <= n - m; i++) {
        if (th1 == ph1 && th2 == ph2) {
            /* Hash match — verify character by character */
            if (memcmp(t + i, p, (size_t)m) == 0) {
                if (count < max_results)
                    results[count] = i;
                count++;
            }
        }
        /* Roll the hash */
        if (i < n - m) {
            th1 = (th1 + RK_MOD1 - (t[i] * pow1) % RK_MOD1) % RK_MOD1;
            th1 = (th1 * RK_BASE1 + t[i + m]) % RK_MOD1;

            th2 = (th2 + RK_MOD2 - (t[i] * pow2) % RK_MOD2) % RK_MOD2;
            th2 = (th2 * RK_BASE2 + t[i + m]) % RK_MOD2;
        }
    }

    *duration_ms = now_ms() - t0;
    return count;
}

/* =========================================================================
   4.  Shift-Or / Bitap
   ========================================================================= */

APME_EXPORT int apme_shift_or(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int* results, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();

    /* For patterns longer than 64 bytes, fall back to KMP */
    if (pattern_len > 64) {
        int count = apme_kmp(text, text_len, pattern, pattern_len,
                             results, max_results, duration_ms);
        /* Override duration to include our dispatch overhead */
        *duration_ms = now_ms() - t0;
        return count;
    }

    if (!text || !pattern || pattern_len <= 0 || text_len < pattern_len) {
        *duration_ms = now_ms() - t0;
        return 0;
    }

    const unsigned char* t = (const unsigned char*)text;
    const unsigned char* p = (const unsigned char*)pattern;
    int n = text_len, m = pattern_len;
    int count = 0;

    /* Build pattern mask: D[c] has bit i SET if p[i] != c */
    uint64_t D[256];
    for (int i = 0; i < 256; i++) D[i] = ~0ULL;
    for (int i = 0; i < m; i++)   D[(int)p[i]] &= ~(1ULL << i);

    uint64_t state = ~0ULL;
    uint64_t match_bit = 1ULL << (m - 1);

    for (int i = 0; i < n; i++) {
        /* Correct Shift-Or update: shift existing state left, then OR the
           character mask.  Bit j in state is 0 iff the last j+1 characters
           of text[0..i] match pattern[0..j].  No manual "| 1" needed — the
           new-alignment opportunity at bit-0 is encoded in D[c][0] = 0
           when t[i] == p[0]. */
        state = (state << 1) | D[(int)t[i]];
        if (!(state & match_bit)) {
            int pos = i - m + 1;
            if (count < max_results)
                results[count] = pos;
            count++;
        }
    }

    *duration_ms = now_ms() - t0;
    return count;
}

/* =========================================================================
   5.  Aho-Corasick (multi-pattern)
   ========================================================================= */

#define AC_MAX_NODES 131072   /* 128K nodes; supports up to ~128K total pattern bytes */
#define AC_ALPHA      256

typedef struct {
    int  ch[AC_ALPHA];  /* children: -1 = absent */
    int  fail;          /* failure link */
    int  out;           /* pattern index of complete match, or -1 */
    int  out_link;      /* linked list of additional output patterns via suffix link */
} AcNode;

static AcNode* ac_nodes = NULL;
static int     ac_size  = 0;

static int ac_new_node(void) {
    if (ac_size >= AC_MAX_NODES) return -1;
    int id = ac_size++;
    memset(ac_nodes[id].ch, -1, sizeof(ac_nodes[id].ch));
    ac_nodes[id].fail     = 0;
    ac_nodes[id].out      = -1;
    ac_nodes[id].out_link = -1;
    return id;
}

APME_EXPORT int apme_aho_corasick(
    const char* text, int text_len,
    const char** patterns, const int* pat_lengths, int num_patterns,
    int* results, int* pattern_ids, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();
    int count = 0;

    if (!text || !patterns || num_patterns <= 0 || text_len <= 0) {
        *duration_ms = now_ms() - t0;
        return 0;
    }

    /* --- Allocate trie -------------------------------------------------- */
    ac_nodes = (AcNode*)malloc(AC_MAX_NODES * sizeof(AcNode));
    if (!ac_nodes) { *duration_ms = 0; return -1; }
    ac_size = 0;

    if (ac_new_node() < 0) { free(ac_nodes); return -1; }  /* root = 0 */

    /* --- Build trie ------------------------------------------------------- */
    for (int pi = 0; pi < num_patterns; pi++) {
        const unsigned char* p = (const unsigned char*)patterns[pi];
        int m = pat_lengths[pi];
        int cur = 0;
        for (int j = 0; j < m; j++) {
            int c = (int)p[j];
            if (ac_nodes[cur].ch[c] == -1) {
                int nid = ac_new_node();
                if (nid < 0) { free(ac_nodes); return -1; }
                ac_nodes[cur].ch[c] = nid;
            }
            cur = ac_nodes[cur].ch[c];
        }
        if (ac_nodes[cur].out == -1)
            ac_nodes[cur].out = pi;  /* first pattern that ends here */
        /* For simplicity, only keep one pattern per terminal node.
           If multiple patterns end at the same node, the shorter duplicate
           is noted via out_link (filled during BFS). */
    }

    /* --- BFS: failure links ---------------------------------------------- */
    int* queue = (int*)malloc((size_t)ac_size * sizeof(int));
    if (!queue) { free(ac_nodes); return -1; }

    int head = 0, tail = 0;

    /* Root's children: fail = root */
    for (int c = 0; c < AC_ALPHA; c++) {
        int child = ac_nodes[0].ch[c];
        if (child == -1) {
            ac_nodes[0].ch[c] = 0;  /* loop back to root */
        } else {
            ac_nodes[child].fail = 0;
            queue[tail++] = child;
        }
    }

    while (head < tail) {
        int u = queue[head++];
        /* Propagate out_link from failure chain */
        int f = ac_nodes[u].fail;
        if (ac_nodes[u].out_link == -1)
            ac_nodes[u].out_link = (ac_nodes[f].out != -1) ? f : ac_nodes[f].out_link;

        for (int c = 0; c < AC_ALPHA; c++) {
            int v = ac_nodes[u].ch[c];
            if (v == -1) {
                /* goto-function: redirect to fail's goto */
                ac_nodes[u].ch[c] = ac_nodes[ac_nodes[u].fail].ch[c];
            } else {
                ac_nodes[v].fail = ac_nodes[ac_nodes[u].fail].ch[c];
                queue[tail++] = v;
            }
        }
    }
    free(queue);

    /* --- Search ---------------------------------------------------------- */
    const unsigned char* t = (const unsigned char*)text;
    int state = 0;
    for (int i = 0; i < text_len && count < max_results; i++) {
        state = ac_nodes[state].ch[(int)t[i]];
        /* Collect all outputs at this state */
        int tmp = state;
        while (tmp > 0) {
            if (ac_nodes[tmp].out != -1) {
                int pi = ac_nodes[tmp].out;
                int pos = i - pat_lengths[pi] + 1;
                if (count < max_results) {
                    results[count]     = pos;
                    pattern_ids[count] = pi;
                }
                count++;
            }
            tmp = ac_nodes[tmp].out_link;
        }
    }

    free(ac_nodes);
    ac_nodes = NULL;
    *duration_ms = now_ms() - t0;
    return count;
}

/* =========================================================================
   6.  Fuzzy search
       - Pattern <= 64 bytes: Wu-Manber k-error bitap (substitutions only).
       - Pattern  > 64 bytes: Levenshtein sliding-window DP (subs+ins+del).
   ========================================================================= */

/* --- Wu-Manber bitap for k errors (substitutions only) ------------------ */
static int fuzzy_bitap(
    const unsigned char* t, int n,
    const unsigned char* p, int m,
    int k,
    int* results, int max_results)
{
    int count = 0;

    /* D[c] has bit i set if p[i] == c  (note: inverted sense vs shift-or) */
    uint64_t D[256];
    memset(D, 0, sizeof(D));
    for (int i = 0; i < m; i++) D[(int)p[i]] |= (1ULL << i);

    /* R[e] = bitmask of active positions with exactly e errors */
    uint64_t* R = (uint64_t*)calloc((size_t)(k + 1), sizeof(uint64_t));
    if (!R) return -1;

    uint64_t match_bit = 1ULL << (m - 1);

    for (int i = 0; i < n; i++) {
        uint64_t old_r = 1ULL;   /* R[-1] = 1 (the "start" state) */
        for (int e = 0; e <= k; e++) {
            uint64_t prev_r = R[e];
            /* Shift + character match (substitution from prev error level) */
            R[e] = ((R[e] << 1) | old_r) & D[(int)t[i]];
            /* Substitution: use old R[e-1] to allow one more error */
            if (e > 0) R[e] |= (old_r << 1);
            old_r = prev_r;

            if (R[e] & match_bit) {
                int start = i - m + 1;
                if (start < 0) start = 0;
                if (count < max_results)
                    results[count] = i;   /* end byte offset */
                count++;
                break;  /* report earliest error level for this position */
            }
        }
    }

    free(R);
    return count;
}

/* --- Levenshtein sliding-window for long patterns ----------------------- */
static int fuzzy_levenshtein(
    const unsigned char* t, int n,
    const unsigned char* p, int m,
    int k,
    int* results, int max_results)
{
    int count = 0;
    /* Allocate two rows for DP */
    int* prev = (int*)malloc((size_t)(m + 1) * sizeof(int));
    int* curr = (int*)malloc((size_t)(m + 1) * sizeof(int));
    if (!prev || !curr) { free(prev); free(curr); return -1; }

    /* Initialise: matching pattern against empty prefix of text (insertions) */
    for (int j = 0; j <= m; j++) prev[j] = j;

    for (int i = 1; i <= n; i++) {
        curr[0] = 0;  /* we can start a match at any position in text */
        for (int j = 1; j <= m; j++) {
            int sub = prev[j - 1] + (t[i - 1] == p[j - 1] ? 0 : 1);
            int del = prev[j] + 1;
            int ins = curr[j - 1] + 1;
            curr[j] = sub < del ? sub : del;
            if (ins < curr[j]) curr[j] = ins;
        }
        /* Full pattern matched with <= k errors */
        if (curr[m] <= k) {
            if (count < max_results)
                results[count] = i - 1;   /* end byte offset of match */
            count++;
        }
        /* Swap rows */
        int* tmp = prev; prev = curr; curr = tmp;
    }

    free(prev); free(curr);
    return count;
}

APME_EXPORT int apme_fuzzy(
    const char* text, int text_len,
    const char* pattern, int pattern_len,
    int max_errors,
    int* results, int max_results,
    double* duration_ms)
{
    double t0 = now_ms();

    if (!text || !pattern || pattern_len <= 0 || text_len <= 0) {
        *duration_ms = now_ms() - t0;
        return 0;
    }
    if (max_errors < 0) max_errors = 0;

    const unsigned char* t = (const unsigned char*)text;
    const unsigned char* p = (const unsigned char*)pattern;
    int count;

    if (pattern_len <= 64) {
        count = fuzzy_bitap(t, text_len, p, pattern_len, max_errors,
                            results, max_results);
    } else {
        count = fuzzy_levenshtein(t, text_len, p, pattern_len, max_errors,
                                  results, max_results);
    }

    *duration_ms = now_ms() - t0;
    return count;
}
