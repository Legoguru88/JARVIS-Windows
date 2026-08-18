"""diagnose why llama.dll fails to load: reliable import-table dump via pefile."""
import ctypes
import os
import subprocess
import sys

FULL = os.path.expandvars(r"%LOCALAPPDATA%\Temp")


def ensure_pefile():
    try:
        import pefile  # noqa: F401
        return True
    except ImportError:
        pass
    print("installing pefile ...")
    ok = subprocess.run(
        [sys.executable, "-m", "pip", "install", "-q", "pefile"],
        capture_output=True,
    ).returncode == 0
    return ok


def main():
    if not ensure_pefile():
        print("could not install pefile; falling back to verbose ctypes load")
        _ctypes_probe()
        return
    import pefile

    pkg = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        ".build", ".venv", "Lib", "site-packages", "llama_cpp", "lib", "llama.dll",
    )
    if not os.path.exists(pkg):
        print(f"llama.dll NOT at {pkg}")
        sys.exit(1)

    print("llama.dll:", pkg)
    print("size:", os.path.getsize(pkg))

    try:
        pe = pefile.PE(pkg, fast_load=True)
        pe.parse_data_directories(directories=[
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
            pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
        ])
    except Exception as e:
        print("pefile parse error:", e)
        _ctypes_probe()
        return

    imports = set()
    for entry in getattr(pe, "DIRECTORY_ENTRY_IMPORT", []) or []:
        imports.add(entry.dll.decode(errors="replace"))
        for imp in entry.imports:
            pass
    for entry in getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []) or []:
        imports.add(entry.dll.decode(errors="replace"))

    print("\nimported DLLs:")
    for d in sorted(imports):
        print("  ", d)

    if not imports:
        print("  (none found - likely fully static, e.g. /MT MSVC runtime)")
        print("  then only the DLL itself or its absence explains the load failure")

    print("\ntrying to load the DLL directly ...")
    _ctypes_probe()

    print("\nresolvability of its imports:")
    for d in sorted(imports):
        lo = d.lower()
        if not lo.endswith((".dll", ".sys")):
            continue
        try:
            ctypes.WinDLL(ctypes.util.find_library(d) or d)
            print(f"  OK    {d}")
        except OSError:
            print(f"  MISS  {d}")


def _ctypes_probe():
    paths = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     ".build", ".venv", "Lib", "site-packages", "llama_cpp", "lib"),
        FULL,
    ]
    for base in paths:
        dll = os.path.join(base, "llama.dll")
        if not os.path.exists(dll):
            continue
        try:
            ctypes.CDLL(os.path.abspath(dll))
            print(f"  LOADED OK  {dll}")
        except OSError as e:
            print(f"  FAIL (winerror={e.winerror})  {dll}")
            print(f"    {e}")
        return
    print(f"  llama.dll not found in {paths}")


if __name__ == "__main__":
    main()