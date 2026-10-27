"""Phase 1.5: exact reverse of DwPr zone structure. stdout <= 45 lines; details -> workspace/recon_state.json"""
import json, os, re, struct, sys, zipfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dwp_lib as L

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WS = os.path.join(ROOT, "workspace")
REF = os.path.join(WS, "samples_ref")
B = "Payload/FL Studio Mobile.app/DirectWave Samples/"
out = []
P = out.append

z = zipfile.ZipFile(os.path.join(ROOT, "target.ipa"))
names = {i.filename.lower(): i for i in z.infolist()}
dwps = [i for i in z.infolist() if i.filename.endswith(".dwp")]

# 1. extra donors (8-25 KB, other categories) + locate Praise samples
os.makedirs(REF, exist_ok=True)
want = [("Guitar", "Purity Guitar"), ("Synth Key", "Ogun Clockwork"), ("Keyboard", "Morphine Clavinet")]
for c, n in want:
    open(os.path.join(REF, n + ".dwp"), "wb").write(z.read(B + c + "/" + n + ".dwp"))
pr = L.parse(z.read(B + "Synth Pad/Praise.dwp"))
ppath = dict(pr["zones"][0])[L.Z_PATH].decode()
base = re.split(r"[\\/]", ppath)[-1]
found = [i.filename for i in z.infolist() if i.filename.lower().endswith("/" + base.lower())]
P("Praise ref wav '%s' -> %s" % (base, found))

# 2. survey all .dwp
stats = Counter(); fmt_ok = 0
res_ok = res_n = 0
key_samples = []   # (root,low,high,lovel,hivel, tail, name)
info_vals = Counter(); loop_rel = Counter(); size_rows = []
file_zones = []
for i in dwps:
    d = z.read(i)
    try:
        S = L.parse(d)
    except Exception as e:
        stats["parse_fail"] += 1; continue
    fmt_ok += 1
    assert struct.unpack_from("<Q", d, L.OFF_PAYLOAD)[0] == len(d) - L.HDR_LEN
    stats["numzones_match"] += S["num_zones"] == len(S["zones"])
    stats["end_tag_last"] += S["top"][-1][0] == L.T_END
    stats["key_len25"] += all(len(dict(k).get(L.Z_KEY, b"")) == 25 for k in S["zones"])
    stats["info_len40"] += all(len(dict(k).get(L.Z_INFO, b"")) == 40 for k in S["zones"])
    stem = i.filename[:-4]
    zs = []
    for k in S["zones"]:
        kd = dict(k)
        kb = kd[L.Z_KEY]
        nm = kd[L.Z_NAME].decode("latin1"); pth = kd[L.Z_PATH].decode("latin1")
        bn = re.split(r"[\\/]", pth)[-1]
        res_n += 1
        res_ok += (stem + "/" + bn).lower() in names
        fr, a, b_, rate, c, ls, le, e1, e2 = struct.unpack("<QIIfIIIII", kd[L.Z_INFO])
        info_vals[(a, b_, c, e1, e2)] += 1
        loop_rel["ls<le<=frames" if 0 < ls < le <= fr else ("zero" if ls == le == 0 else "other")] += 1
        zs.append((kb, nm))
    file_zones.append((i.filename, zs))
P("Parsed %d/%d .dwp; num_zones@0x4A ok=%d; payload_len@0x28==size-0x30 ok; END tag last=%d" % (
    fmt_ok, len(dwps), stats["numzones_match"], stats["end_tag_last"]))
P("0x1F4 always 25 B in %d files; 0x1F7 always 40 B in %d" % (stats["key_len25"], stats["info_len40"]))
P("Sample resolution <dwp stem>/<basename> exists: %d/%d zones" % (res_ok, res_n))

# 3. find offsets of Root/Low/High/LoVel/HiVel by invariants over all zones
best = []
var_off = [o for o in range(8) if len({kb[o] for _, zs in file_zones for kb, _ in zs}) > 8]  # non-constant bytes only
for ro in var_off:
    for lo in var_off:
        for hi in var_off:
            if len({ro, lo, hi}) < 3: continue
            ok = tot = 0
            for fn, zs in file_zones:
                for kb, nm in zs:
                    tot += 1
                    ok += kb[lo] <= kb[ro] <= kb[hi] <= 127
            best.append((ok / tot, ro, lo, hi))
best.sort(reverse=True)
top = best[0]
RO, LO, HI = top[1:]
# adjacency: sorted by root, next.low == prev.high+1
adj = tot = 0; hv = Counter(); lv = Counter()
for fn, zs in file_zones:
    ks = sorted((kb for kb, _ in zs), key=lambda k: (k[RO], k[HI]))
    for a, b in zip(ks, ks[1:]):
        if b[LO] != a[LO] or b[HI] != a[HI]:
            tot += 1; adj += b[LO] == a[HI] + 1
    for kb, _ in zs: hv[kb[4]] += 1; lv[kb[3]] += 1
# velocity offsets
vel = {}
for off in range(8):
    vel[off] = Counter(kb[off] for _, zs in file_zones for kb, _ in zs).most_common(2)
# note-name check on Purity Guitar
NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}
pg = L.parse(open(os.path.join(REF, "Purity Guitar.dwp"), "rb").read())
chk = []
for k in pg["zones"]:
    kd = dict(k); m = re.search(r"_([A-G]#?)(\d)$", kd[L.Z_NAME].decode())
    chk.append(kd[L.Z_KEY][RO] - (12 * (int(m.group(2)) + 3) + NOTE[m.group(1)]))
P("Key invariants: low<=root<=high<=127 hold %.1f%% at offsets root=%d low=%d high=%d" % (top[0] * 100, RO, LO, HI))
P("Adjacency Next.low==Prev.high+1: %d/%d; root-vs-name offset (midi=12*(oct+3)+pc) diffs=%s" % (adj, tot, sorted(set(chk))))
P("Key block byte values (off: top2): " + "; ".join("%d:%s" % (o, [v for v, _ in c]) for o, c in vel.items() if o in (3, 4, 5)))

# 4. fixed vs variable
rows = []
for k in pg["zones"]:
    kd = dict(k); n = len(kd[L.Z_NAME]); p_ = len(kd[L.Z_PATH])
    total = sum(12 + len(v) for _, v in k)
    rows.append(total - n - p_)
P("Zone = TLV (u32 tag, u64 len): VARIABLE length. zone_bytes - len(name) - len(path) const = %s" % sorted(set(rows)))
P("Zone container header 12 B; children: 0x1F4(25) 0x1F5(name) 0x1F6(path) 0x1F7(40) ...; ends 0x04 len 0")
P("0x1F7 = u64 frames,u32 chan,u32 blk,f32 rate,u32,u32 loopS,u32 loopE,u32,u32. loops: %s" % dict(loop_rel))
P("0x1F7 const fields (a,b,c,e1,e2) top: %s" % info_vals.most_common(3))
fl = z.read(B + "Guitar/Purity Guitar/Pur_A1.wav")[:4]
P(".wav in ipa is really: %s (FLAC) -> output audio must be FLAC-in-.wav" % fl)

spec = {
    "header": {"magic": "DwPr", "fixed_bytes": L.FIXED_END, "payload_len_u64@": L.OFF_PAYLOAD,
               "payload_len_formula": "file_size-0x30", "num_zones_u32@": L.OFF_NUMZONES},
    "tag_stream": "[u32 tag][u64 len][data] from 0x5A", "name_tag": 0x66, "path_tag": 0x67,
    "zone_container_tag": 3, "end_tag": 2,
    "zone_children": {"0x1F4": {"len": 25, "root": RO, "low": LO, "high": HI, "lovel": 3, "hivel": 4},
                      "0x1F5": "sample name", "0x1F6": "sample path (u64 len-prefixed)",
                      "0x1F7": {"len": 40, "frames_u64@": 0, "channels_u32@": 8, "peakblock_u32@": 12, "rate_f32@": 16,
                              "loopmode_u32@": 20, "loop_start_u32@": 24, "loop_end_u32@": 28}},
    "sample_resolution": "<dwp dir>/<dwp stem>/<basename of 0x1F6 path>", "audio": "FLAC data inside .wav",
    "variable_length": True, "stats": dict(stats), "survey_files": len(dwps), "praise_wav": found}
st = json.load(open(os.path.join(WS, "recon_state.json")))
st["dwpr_spec"] = spec
json.dump(st, open(os.path.join(WS, "recon_state.json"), "w"), indent=1, default=str)
P("Spec saved: workspace/recon_state.json[dwpr_spec]")
print("\n".join(out[:45]))
