"""Stage 1.6 Step 2: Stream-inspect Mach-O imports, LC_RPATH, symbol table, LC_DYLD_INFO bind opcodes,
and LC_DYLD_CHAINED_FIXUPS of 'Payload/FL Studio Mobile.app/FL Studio Mobile' inside target.ipa.
Pure Python stdlib (struct, zipfile), stdout <= 30 lines.
"""
import struct
import zipfile

IPA_PATH = "target.ipa"
BIN_PATH = "Payload/FL Studio Mobile.app/FL Studio Mobile"

LC_SYMTAB = 0x02
LC_DYSYMTAB = 0x0B
LC_LOAD_DYLIB = 0x0C
LC_LOAD_WEAK_DYLIB = 0x80000018
LC_RPATH = 0x8000001C
LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_CHAINED_FIXUPS = 0x80000034


def read_slice_from_zip(zf, arcname, offset, size):
    with zf.open(arcname, "r") as f:
        rem = offset
        while rem > 0:
            chunk = f.read(min(65536, rem))
            if not chunk:
                break
            rem -= len(chunk)
        return f.read(size)


def parse_dyld_bind_opcodes(blob):
    """Extract symbol names from classic dyld bind / lazy_bind opcode stream (BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM = 0x40)."""
    syms = []
    i, n = 0, len(blob)
    while i < n:
        op = blob[i] & 0xF0
        imm = blob[i] & 0x0F
        i += 1
        if op == 0x40:  # BIND_OPCODE_SET_SYMBOL_TRAILING_FLAGS_IMM
            end = blob.find(b"\x00", i)
            if end == -1:
                break
            s = blob[i:end].decode("utf-8", errors="replace").lstrip("_")
            if s:
                syms.append(s)
            i = end + 1
        elif op in (0x10, 0x20, 0x50, 0x70, 0x80):  # ULEB128 operand
            if op == 0x20 and imm != 1:
                continue
            while i < n and (blob[i] & 0x80):
                i += 1
            i += 1
        elif op == 0xC0:  # two ULEB128 operands
            for _ in range(2):
                while i < n and (blob[i] & 0x80):
                    i += 1
                i += 1
    return syms


def parse_chained_fixups_imports(blob):
    if len(blob) < 28:
        return []
    _, _, imports_off, symbols_off, imports_cnt, imports_fmt, symbols_fmt = struct.unpack_from("<7I", blob, 0)
    if symbols_fmt != 0 or imports_cnt == 0:
        return []
    names = []
    pos = imports_off
    for _ in range(imports_cnt):
        if imports_fmt == 1:
            val = struct.unpack_from("<I", blob, pos)[0]
            name_off = (val >> 9) & 0x7FFFFF
            pos += 4
        elif imports_fmt == 2:
            val = struct.unpack_from("<I", blob, pos)[0]
            name_off = (val >> 9) & 0x7FFFFF
            pos += 8
        elif imports_fmt == 3:
            val = struct.unpack_from("<Q", blob, pos)[0]
            name_off = (val >> 32) & 0xFFFFFFFF
            pos += 16
        else:
            break
        s_start = symbols_off + name_off
        s_end = blob.find(b"\x00", s_start)
        if s_start < len(blob) and s_end != -1:
            names.append(blob[s_start:s_end].decode("utf-8", errors="replace").lstrip("_"))
    return names


def main():
    with zipfile.ZipFile(IPA_PATH, "r") as zf:
        head = read_slice_from_zip(zf, BIN_PATH, 0, 16384)
        magic, _, _, _, ncmds, szcmds, _, _ = struct.unpack_from("<8I", head, 0)

        rpaths = []
        symtab_info = None
        chained_info = None
        dyld_info = None

        pos = 32
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", head, pos)
            if cmd == LC_RPATH:
                soff = struct.unpack_from("<I", head, pos + 8)[0]
                rpaths.append(head[pos + soff : pos + cmdsize].split(b"\x00", 1)[0].decode("utf-8", errors="replace"))
            elif cmd == LC_SYMTAB:
                symtab_info = struct.unpack_from("<4I", head, pos + 8)
            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                chained_info = struct.unpack_from("<2I", head, pos + 8)
            elif cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
                dyld_info = struct.unpack_from("<10I", head, pos + 8)
            pos += cmdsize

        all_symbols = set()
        mechanisms = []

        if symtab_info:
            symoff, nsyms, stroff, strsize = symtab_info
            sym_bytes = read_slice_from_zip(zf, BIN_PATH, symoff, nsyms * 16)
            str_bytes = read_slice_from_zip(zf, BIN_PATH, stroff, strsize)
            for i in range(nsyms):
                n_strx, n_type, _, _, _ = struct.unpack_from("<IBBHQ", sym_bytes, i * 16)
                if (n_type & 0x0E) == 0x00 and n_strx < len(str_bytes):
                    end = str_bytes.find(b"\x00", n_strx)
                    if end != -1:
                        all_symbols.add(str_bytes[n_strx:end].decode("utf-8", errors="replace").lstrip("_"))
            mechanisms.append(f"LC_SYMTAB(undef={len(all_symbols)})")

        if dyld_info:
            _, _, bind_off, bind_sz, _, _, lazy_off, lazy_sz, _, _ = dyld_info
            b_syms = parse_dyld_bind_opcodes(read_slice_from_zip(zf, BIN_PATH, bind_off, bind_sz)) if bind_sz else []
            l_syms = parse_dyld_bind_opcodes(read_slice_from_zip(zf, BIN_PATH, lazy_off, lazy_sz)) if lazy_sz else []
            all_symbols.update(b_syms)
            all_symbols.update(l_syms)
            mechanisms.append(f"LC_DYLD_INFO_ONLY(bind={len(b_syms)}, lazy={len(l_syms)})")

        if chained_info and chained_info[1] > 0:
            c_names = parse_chained_fixups_imports(read_slice_from_zip(zf, BIN_PATH, chained_info[0], chained_info[1]))
            all_symbols.update(c_names)
            mechanisms.append(f"LC_DYLD_CHAINED_FIXUPS(imports={len(c_names)})")

    targets = [
        "AudioUnitSetProperty",
        "AudioUnitGetProperty",
        "AudioUnitRender",
        "AudioOutputUnitStart",
        "AudioOutputUnitStop",
        "AudioComponentInstanceNew",
        "AudioUnitInitialize",
    ]
    print(f"Mach-O Binding: {', '.join(mechanisms)} | Unique imports: {len(all_symbols)}")
    print(f"LC_RPATH: {rpaths}")
    for t in targets:
        print(f"  {t:<26} : {'IMPORTED' if t in all_symbols else 'MISSING'}")
    augraph = sorted(s for s in all_symbols if s.startswith("AUGraph"))
    aq = sorted(s for s in all_symbols if s.startswith("AudioQueue"))
    av = sorted(s for s in all_symbols if "AVAudio" in s)
    print(f"AUGraph*: {len(augraph)} | AudioQueue*: {len(aq)} | AVAudioEngine: {sum('Engine' in s for s in av)} | AVAudioSession: {len(av)}")
    ok = all(k in all_symbols for k in ("AudioUnitSetProperty", "AudioUnitRender", "AudioOutputUnitStart"))
    print(f"CONCLUSION: fishhook + RemoteIO AudioUnit hook is {'100% SUITABLE' if ok else 'NOT SUITABLE'}")


if __name__ == "__main__":
    main()
