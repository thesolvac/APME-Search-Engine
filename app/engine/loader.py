"""
ctypes loader for the APME shared library.

Call get_lib() to obtain the loaded ctypes.CDLL instance.
The first call compiles the library if needed (requires gcc).
"""

import ctypes
import os
import sys
import subprocess

_lib = None

_HERE      = os.path.dirname(os.path.abspath(__file__))
_ROOT      = os.path.abspath(os.path.join(_HERE, "..", ".."))
_ENGINE_DIR = os.path.join(_ROOT, "c_engine")
_LIB_NAME  = "apme_engine.dll" if sys.platform == "win32" else "apme_engine.so"
_LIB_PATH  = os.path.join(_ENGINE_DIR, _LIB_NAME)


def _compile():
    """Run build.py to produce the shared library."""
    build_script = os.path.join(_ENGINE_DIR, "build.py")
    result = subprocess.run(
        [sys.executable, build_script],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"C engine compilation failed:\n{result.stderr}"
        )
    print(result.stdout.strip())


def _setup_signatures(lib: ctypes.CDLL) -> None:
    """Declare argtypes and restype for every exported function."""
    c_int_p   = ctypes.POINTER(ctypes.c_int)
    c_double_p = ctypes.POINTER(ctypes.c_double)
    c_char_p  = ctypes.c_char_p

    # apme_kmp / apme_boyer_moore / apme_rabin_karp / apme_shift_or
    for name in ("apme_kmp", "apme_boyer_moore", "apme_rabin_karp", "apme_shift_or"):
        fn = getattr(lib, name)
        fn.restype  = ctypes.c_int
        fn.argtypes = [
            c_char_p, ctypes.c_int,   # text, text_len
            c_char_p, ctypes.c_int,   # pattern, pattern_len
            c_int_p,  ctypes.c_int,   # results[], max_results
            c_double_p,               # duration_ms (out)
        ]

    # apme_aho_corasick
    lib.apme_aho_corasick.restype  = ctypes.c_int
    lib.apme_aho_corasick.argtypes = [
        c_char_p, ctypes.c_int,                          # text, text_len
        ctypes.POINTER(c_char_p), c_int_p, ctypes.c_int, # patterns[], pat_lengths[], num_patterns
        c_int_p, c_int_p, ctypes.c_int,                  # results[], pattern_ids[], max_results
        c_double_p,                                       # duration_ms
    ]

    # apme_fuzzy
    lib.apme_fuzzy.restype  = ctypes.c_int
    lib.apme_fuzzy.argtypes = [
        c_char_p, ctypes.c_int,   # text, text_len
        c_char_p, ctypes.c_int,   # pattern, pattern_len
        ctypes.c_int,             # max_errors
        c_int_p, ctypes.c_int,   # results[], max_results
        c_double_p,               # duration_ms
    ]

    # apme_version
    lib.apme_version.restype  = c_char_p
    lib.apme_version.argtypes = []


def get_lib() -> ctypes.CDLL:
    global _lib
    if _lib is not None:
        return _lib

    if not os.path.exists(_LIB_PATH):
        _compile()

    _lib = ctypes.CDLL(_LIB_PATH)
    _setup_signatures(_lib)
    return _lib
