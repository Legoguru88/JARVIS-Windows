"""diagnose why llama.dll fails to load: probe with DLL search-path fixes."""
import ctypes
import os
import subprocess
import sys

LIBDIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    ".build", ".venv", "Lib", "site-packages", "llama_cpp", "lib",
)
LLAMA = os.path.join(LIBDIR, "llama.dll")


def probe(tag, pre=None):
    print(f"\n[{tag}]")
    if pre:
        pre()
    try:
        h = ctypes.WinDLL(LLAMA)
        print("  LOADED OK ->", LLAMA)
        return True
    except OSError as e:
        print(f"  FAIL (winerror={e.winerror}): {e}")
        print("  -> the missing dep is one llama.dll imports but Windows cannot find")
        return False


def add_libdir():
    try:
        os.add_dll_directory(LIBDIR)
        print(f"  add_dll_directory({LIBDIR})")
    except OSError as e:
        print("  add_dll_directory failed:", e)


def add_system32():
    try:
        os.add_dll_directory(r"C:\Windows\System32")
        print("  add_dll_directory(System32)")
    except OSError as e:
        print("  add_dll_directory(System32) failed:", e)


def check_msvc():
    for dll in ("MSVCP140.dll", "VCRUNTIME140.dll", "VCRUNTIME140_1.dll"):
        try:
            ctypes.WinDLL(dll)
            print(f"  system has {dll}")
        except OSError:
            print(f"  system MISSING {dll}")


def main():
    print("llama.dll:", LLAMA)
    print("lib dir contents:")
    if os.path.isdir(LIBDIR):
        for f in sorted(os.listdir(LIBDIR)):
            fp = os.path.join(LIBDIR, f)
            print(f"   {os.path.getsize(fp):>12,}  {f}")
    else:
        print("   (lib dir missing)")

    ok = probe("plain load", check_msvc)
    if not ok:
        probe("after add_dll_directory(libdir)", add_libdir)
    if not ok:
        probe("after libdir + System32", add_system32)

    # confirm the actual llama_cpp loader path
    print("\nllama_cpp loader version check:")
    try:
        sub = subprocess.run(
            [sys.executable, "-c",
             "import importlib.metadata as m; print(m.version('llama-cpp-python'))"],
            capture_output=True, text=True)
        print("  version:", sub.stdout.strip() or sub.stderr.strip())
    except Exception as e:
        print("  ", e)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()