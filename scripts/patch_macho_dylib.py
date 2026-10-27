"""Pure-Python Mach-O 64-bit LC_LOAD_DYLIB header patcher & verifier (stdlib struct only)."""
import struct

MH_MAGIC_64 = 0xFEEDFACF
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_RPATH = 0x8000001C
MACH_HEADER_64_FMT = "<IIIIIIII"
MACH_HEADER_64_SIZE = 32
DYLIB_CMD_HDR_FMT = "<IIIIII"
DYLIB_CMD_HDR_SIZE = 24


def list_load_dylibs(header_bytes):
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from(MACH_HEADER_64_FMT, header_bytes, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"Unsupported Mach-O magic: 0x{magic:08x} (expected 0xfeedfacf)")
    pos = MACH_HEADER_64_SIZE
    dylibs = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", header_bytes, pos)
        if cmd in (LC_LOAD_DYLIB, LC_LOAD_WEAK_DYLIB):
            str_off = struct.unpack_from("<I", header_bytes, pos + 8)[0]
            raw = header_bytes[pos + str_off : pos + cmdsize]
            path = raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")
            dylibs.append(path)
        pos += cmdsize
    return dylibs


def list_rpaths(header_bytes):
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from(MACH_HEADER_64_FMT, header_bytes, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"Unsupported Mach-O magic: 0x{magic:08x}")
    pos = MACH_HEADER_64_SIZE
    rpaths = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", header_bytes, pos)
        if cmd == LC_RPATH:
            str_off = struct.unpack_from("<I", header_bytes, pos + 8)[0]
            raw = header_bytes[pos + str_off : pos + cmdsize]
            rpaths.append(raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace"))
        pos += cmdsize
    return rpaths


def patch_macho_header(header_bytes, dylib_path="@rpath/FLM_CustomDSP.dylib"):
    """Patch a Mach-O 64-bit header buffer in-place to add LC_LOAD_DYLIB.
    Returns (patched_header_bytes, info_dict). Idempotent if dylib_path already exists.
    """
    buf = bytearray(header_bytes)
    magic, cpu, sub, ft, ncmds, szcmds, flags, res = struct.unpack_from(MACH_HEADER_64_FMT, buf, 0)
    if magic != MH_MAGIC_64:
        raise ValueError(f"Unsupported Mach-O magic: 0x{magic:08x}")

    existing = list_load_dylibs(buf)
    if dylib_path in existing:
        end_off = MACH_HEADER_64_SIZE + szcmds
        first_nz = next((i for i in range(end_off, len(buf)) if buf[i] != 0), len(buf))
        return bytes(buf), {
            "already_present": True,
            "ncmds": ncmds,
            "sizeofcmds": szcmds,
            "dylib_path": dylib_path,
            "free_pad_after": first_nz - end_off,
        }

    path_bytes = dylib_path.encode("utf-8") + b"\x00"
    raw_len = DYLIB_CMD_HDR_SIZE + len(path_bytes)
    cmdsize = (raw_len + 7) & ~7  # 8-byte aligned for 64-bit Mach-O
    pad_len = cmdsize - raw_len

    cmd_offset = MACH_HEADER_64_SIZE + szcmds
    if cmd_offset + cmdsize > len(buf):
        raise ValueError("Header buffer too small for new LC_LOAD_DYLIB command")

    if any(b != 0 for b in buf[cmd_offset : cmd_offset + cmdsize]):
        raise RuntimeError(f"Non-zero bytes found in Mach-O header padding at 0x{cmd_offset:x}")

    cmd_blob = (
        struct.pack(
            DYLIB_CMD_HDR_FMT,
            LC_LOAD_DYLIB,
            cmdsize,
            DYLIB_CMD_HDR_SIZE,
            2,
            0x00010000,
            0x00010000,
        )
        + path_bytes
        + (b"\x00" * pad_len)
    )

    buf[cmd_offset : cmd_offset + cmdsize] = cmd_blob
    new_ncmds = ncmds + 1
    new_szcmds = szcmds + cmdsize
    struct.pack_into(MACH_HEADER_64_FMT, buf, 0, magic, cpu, sub, ft, new_ncmds, new_szcmds, flags, res)

    new_end = MACH_HEADER_64_SIZE + new_szcmds
    first_nz = next((i for i in range(new_end, len(buf)) if buf[i] != 0), len(buf))

    return bytes(buf), {
        "already_present": False,
        "old_ncmds": ncmds,
        "new_ncmds": new_ncmds,
        "old_sizeofcmds": szcmds,
        "new_sizeofcmds": new_szcmds,
        "cmd_offset": cmd_offset,
        "cmdsize": cmdsize,
        "free_pad_after": first_nz - new_end,
        "dylib_path": dylib_path,
    }
