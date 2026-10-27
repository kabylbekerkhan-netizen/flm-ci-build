"""Phase 1: contactless recon of target.ipa (stdlib only, stdout <= 45 lines)."""
import json, os, plistlib, re, struct, zipfile
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IPA = os.path.join(ROOT, "target.ipa")
WS = os.path.join(ROOT, "workspace")
REF = os.path.join(WS, "samples_ref")
EXTS = (".dwp", ".instr", ".flmpst", ".wav")
state = {}
out = []


def p(s):
    out.append(s)


def hexdump(b, n=256):
    rows = []
    for i in range(0, min(len(b), n), 16):
        c = b[i:i + 16]
        rows.append("%04x  %-47s  %s" % (i, " ".join("%02x" % x for x in c),
                                          "".join(chr(x) if 32 <= x < 127 else "." for x in c)))
    return rows


def kind(b):
    if b[:4] == b"PK\x03\x04": return "ZIP"
    if b[:4] in (b"RIFF", b"RIFX"): return "RIFF:" + b[8:12].decode("latin1")
    s = b[:64].lstrip()
    if s[:1] in (b"{", b"["): return "JSON?"
    if s[:5] == b"<?xml" or s[:1] == b"<": return "XML?"
    if b[:8] == b"bplist00": return "binary plist"
    return "custom binary"


def macho(zf, name):
    with zf.open(name) as f:
        head = f.read(4096)
        res = {"read_bytes": len(head)}
        off = 0
        if head[:4] in (b"\xca\xfe\xba\xbe",):  # fat (big endian)
            n = struct.unpack(">I", head[4:8])[0]
            archs = [struct.unpack(">5I", head[8 + 20 * i:28 + 20 * i]) for i in range(n)]
            res["fat_archs"] = [{"cputype": a[0], "offset": a[2]} for a in archs]
            arm64 = [a for a in archs if a[0] == 0x0100000C]
            off = (arm64 or archs)[0][2]
            f.seek(off)
            head = f.read(4096)
        magic = struct.unpack("<I", head[:4])[0]
        if magic != 0xFEEDFACF:
            res["error"] = "unexpected magic %08x" % magic
            return res
        cputype, _, ft, ncmds, szcmds, flags = struct.unpack("<iiIIII", head[4:28])
        res.update(cputype=cputype, ncmds=ncmds, sizeofcmds=szcmds)
        if 32 + szcmds > len(head):  # extend header read if load commands exceed 4096
            head += f.read(32 + szcmds - len(head))
            res["read_bytes"] = len(head) + off
        pos = 32
        dylibs, enc = [], None
        for _ in range(ncmds):
            cmd, sz = struct.unpack("<II", head[pos:pos + 8])
            if cmd in (0xC, 0x80000018, 0xD, 0x1F):  # LOAD/WEAK/REEXPORT/LAZY dylib
                no = struct.unpack("<I", head[pos + 8:pos + 12])[0]
                dylibs.append(head[pos + no:pos + sz].split(b"\0")[0].decode())
            elif cmd == 0x2C:  # LC_ENCRYPTION_INFO_64
                co, cs, cid = struct.unpack("<III", head[pos + 8:pos + 20])
                enc = {"cryptoff": co, "cryptsize": cs, "cryptid": cid}
            pos += sz
        res["encryption_info"] = enc
        res["encrypted"] = None if enc is None else enc["cryptid"] != 0
        res["dylibs"] = dylibs
        return res


def main():
    os.makedirs(REF, exist_ok=True)
    zf = zipfile.ZipFile(IPA)
    infos = zf.infolist()
    names = [i.filename for i in infos]
    state["ipa"] = {"size": os.path.getsize(IPA), "entries": len(names)}

    # 2. Info.plist
    pl_name = next(n for n in names if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n))
    app = pl_name.rsplit("/", 1)[0]
    pl = plistlib.loads(zf.read(pl_name))
    state["info_plist"] = {k: pl.get(k) for k in ("CFBundleIdentifier", "CFBundleExecutable",
                                                  "CFBundleShortVersionString", "CFBundleVersion",
                                                  "MinimumOSVersion")}
    state["info_plist"]["AudioComponents"] = pl.get("AudioComponents")
    state["info_plist"]["UIBackgroundModes"] = pl.get("UIBackgroundModes")
    state["info_plist"]["UIFileSharingEnabled"] = pl.get("UIFileSharingEnabled")
    state["info_plist"]["LSSupportsOpeningDocumentsInPlace"] = pl.get("LSSupportsOpeningDocumentsInPlace")
    state["app_dir"] = app

    # 3. resource map
    by_ext = defaultdict(list)
    all_ext = Counter()
    for i in infos:
        if i.is_dir(): continue
        e = os.path.splitext(i.filename)[1].lower()
        all_ext[e] += 1
        if e in EXTS: by_ext[e].append(i)
    state["counts"] = {e: len(by_ext[e]) for e in EXTS}
    state["top_extensions"] = all_ext.most_common(15)
    state["dirs"] = {e: Counter(os.path.dirname(i.filename) for i in by_ext[e]).most_common(10) for e in EXTS}
    state["smallest"] = {}
    for e in (".dwp", ".instr"):
        sm = sorted(by_ext[e], key=lambda i: i.file_size)[:5]
        state["smallest"][e] = [(i.filename, i.file_size) for i in sm]

    # 4+5. extract + analyze
    state["samples"] = {}
    for e in (".dwp", ".instr"):
        if not by_ext[e]: continue
        i = min(by_ext[e], key=lambda i: i.file_size)
        dest = os.path.join(REF, os.path.basename(i.filename))
        with open(dest, "wb") as f: f.write(zf.read(i))
        d = os.path.dirname(i.filename)
        sib = [s for s in infos if not s.is_dir() and os.path.dirname(s.filename) == d
               and s.filename != i.filename and s.filename.lower().endswith(".wav")][:5]
        for s in sib:
            with open(os.path.join(REF, os.path.basename(s.filename)), "wb") as f: f.write(zf.read(s))
        b = zf.read(i)
        strs = [m.group().decode() for m in re.finditer(rb"[\x20-\x7e]{5,}", b[:8192])][:40]
        utf16 = [m.group().decode("utf-16le") for m in re.finditer(rb"(?:[\x20-\x7e]\x00){5,}", b[:8192])][:40]
        riff_pos = [m.start() for m in re.finditer(rb"RIFF", b)][:10]
        state["samples"][e] = {"path": i.filename, "size": len(b), "kind": kind(b),
                               "hexdump_256": hexdump(b), "ascii_strings": strs, "utf16_strings": utf16,
                               "embedded_RIFF_offsets": riff_pos,
                               "sibling_wavs_extracted": [s.filename for s in sib],
                               "keyzone_note": "see hexdump/strings; keyzone fields need manual reverse-engineering"}

    # 6. Mach-O
    exe = app + "/" + state["info_plist"]["CFBundleExecutable"]
    state["macho"] = macho(zf, exe) if exe in names else {"error": "executable not found"}

    os.makedirs(WS, exist_ok=True)
    with open(os.path.join(WS, "recon_state.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, ensure_ascii=False, default=str)

    # summary
    ip = state["info_plist"]
    p("IPA: %.1f MB, %d entries; app=%s" % (state["ipa"]["size"] / 1e6, len(names), app))
    p("ID=%s exe=%s ver=%s" % (ip["CFBundleIdentifier"], ip["CFBundleExecutable"], ip["CFBundleShortVersionString"]))
    p("AudioComponents=%s UIBackgroundModes=%s" % (bool(ip["AudioComponents"]), ip["UIBackgroundModes"]))
    p("FileSharing=%s OpenInPlace=%s" % (ip["UIFileSharingEnabled"], ip["LSSupportsOpeningDocumentsInPlace"]))
    p("Counts: " + ", ".join("%s=%d" % kv for kv in state["counts"].items()))
    for e in EXTS:
        if state["dirs"][e]: p("  %s top dir: %s (%d)" % (e, *state["dirs"][e][0]))
    for e, lst in state["smallest"].items():
        p("Smallest %s:" % e)
        for n, s in lst: p("  %6d  %s" % (s, n[-70:]))
    for e, s in state["samples"].items():
        p("%s sample: %s, %d B, kind=%s, RIFF@%s, sibs=%d" % (e, os.path.basename(s["path"]), s["size"],
                                                            s["kind"], s["embedded_RIFF_offsets"][:3],
                                                            len(s["sibling_wavs_extracted"])))
    m = state["macho"]
    p("Mach-O: encrypted=%s enc=%s dylibs=%d" % (m.get("encrypted"), m.get("encryption_info"), len(m.get("dylibs", []))))
    fw = [d.split("/")[-1] for d in m.get("dylibs", []) if "/Frameworks/" in d and "System" in d]
    p("Frameworks: " + ", ".join(fw)[:300])
    p("Saved: workspace/recon_state.json")
    print("\n".join(out[:45]))


main()
