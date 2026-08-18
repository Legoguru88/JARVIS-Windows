"""diagnose why llama.dll fails to load: prints its import dependencies."""
import ctypes
import os
import struct
import sys

MSVC = ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll", "msvcp140_1.dll")


def pe_imports(path: str):
    with open(path, "rb") as f:
        data = f.read()

    if data[:2] != b"MZ":
        return ["NOT A PE FILE"]

    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    if data[e_lfanew:e_lfanew + 4] != b"PE\x00\x00":
        return ["BAD PE SIGNATURE"]

    coff = e_lfanew + 4
    opt_ptr = coff + 24
    magic = struct.unpack_from("<H", data, opt_ptr)[0]
    is64 = magic == 0x20B
    opt_size = struct.unpack_from("<H", data, coff + 20)[0]

    num_sections = struct.unpack_from("<H", data, coff + 2)[0]
    section_ptr = coff + 24 + opt_size
    sections = []
    for i in range(num_sections):
        off = section_ptr + i * 40
        name = data[off:off + 8].rstrip(b"\x00").decode("latin1")
        vsize = struct.unpack_from("<I", data, off + 8)[0]
        vaddr = struct.unpack_from("<I", data, off + 12)[0]
        raw_size = struct.unpack_from("<I", data, off + 16)[0]
        raw_ptr = struct.unpack_from("<I", data, off + 20)[0]
        sections.append((name, vaddr, vsize, raw_ptr, raw_size))

    def rva_to_off(rva):
        for name, vaddr, vsize, raw_ptr, raw_size in sections:
            if vaddr <= rva < vaddr + max(vsize, raw_size):
                return raw_ptr + (rva - vaddr)
        return None

    dd_off = opt_ptr + (112 if is64 else 96)
    imp_rva, _ = struct.unpack_from("<II", data, dd_off)  # dir 1 = imports
    if not imp_rva:
        return ["NO IMPORT TABLE"]

    out, off = [], rva_to_off(imp_rva)
    while off is not None:
        name_rva = struct.unpack_from("<I", data, off + 12)[0]
        if not name_rva:
            break
        n_off = rva_to_off(name_rva)
        end = data.index(b"\x00", n_off)
        out.append(data[n_off:end].decode("latin1"))
        off += 20
    return out


def main():
    pkg = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".build", ".venv", "Lib", "site-packages", "llama_cpp", "lib", "llama.dll",
    )
    if not os.path.exists(pkg):
        print(f"llama.dll NOT at {pkg}")
        sys.exit(1)

    print("llama.dll:", pkg)
    deps = pe_imports(pkg)
    if not deps:
        print("could not parse imports")
        return

    print("\nllama.dll depends on:")
    for d in deps:
        print("  ", d)

    interesting = [d for d in deps if any(k in d.lower() for k in
        ("cudart", "cublas", "cudnn", "cuda", "nvidia", "nvrtc", "ggml",
         "vcruntime", "msvcp", "concrt", "ucrt", "libomp", "libgomp"))]
    if not interesting:
        interesting = deps

    print("\nresolve check:")
    for d in interesting:
        lo = d.lower()
        if not lo.endswith(".dll"):
            continue
        try:
            ctypes.WinDLL(d)
            print(f"  OK    {d}")
        except OSError:
            print(f"  MISS  {d}")

    print("\nMSVC runtime present in System32?")
    for d in MSVC:
        try:
            ctypes.WinDLL(ctypes.util.find_library(d) or d)
            print(f"  OK    {d}")
        except (OSError, AttributeError):
            print(f"  MISS  {d}")


if __name__ == "__main__":
    main()