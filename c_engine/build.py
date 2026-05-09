"""
Build script for the APME C engine shared library.

Usage:
    python c_engine/build.py

Outputs:
    c_engine/apme_engine.dll   (Windows)
    c_engine/apme_engine.so    (Linux / macOS)

Requirements:
    GCC must be on PATH.  On Windows install via:
        - MinGW-w64  (https://www.mingw-w64.org/)
        - MSYS2      (pacman -S mingw-w64-x86_64-gcc)
        - WinLibs    (https://winlibs.com/)
"""

import subprocess
import sys
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
SRC  = os.path.join(HERE, "apme_engine.c")

if sys.platform == "win32":
    OUT   = os.path.join(HERE, "apme_engine.dll")
    FLAGS = [
        "gcc", "-shared", "-O2", "-march=native",
        "-fvisibility=hidden",
        "-DAPME_EXPORT=__declspec(dllexport)",
        "-o", OUT, SRC,
        "-lws2_32",          # needed on Windows for some timer APIs
    ]
else:
    OUT   = os.path.join(HERE, "apme_engine.so")
    FLAGS = [
        "gcc", "-shared", "-fPIC", "-O2", "-march=native",
        "-fvisibility=hidden",
        "-o", OUT, SRC,
        "-lm",
    ]


def main():
    if not shutil.which("gcc"):
        print("[ERROR] gcc not found on PATH.")
        print("  Windows: install MinGW-w64 or MSYS2 and add to PATH.")
        print("  Linux  : sudo apt install build-essential")
        print("  macOS  : xcode-select --install")
        sys.exit(1)

    print(f"[BUILD] Compiling {os.path.basename(SRC)} → {os.path.basename(OUT)}")
    print("  " + " ".join(FLAGS))

    result = subprocess.run(FLAGS, capture_output=True, text=True)

    if result.returncode != 0:
        print("[ERROR] Compilation failed:")
        print(result.stderr)
        sys.exit(1)

    size_kb = os.path.getsize(OUT) / 1024
    print(f"[OK]    {OUT}  ({size_kb:.1f} KB)")


if __name__ == "__main__":
    main()
