"""Phase 2: build DirectWave multi-instruments (.dwp + FLAC samples) using a factory .dwp as binary donor.
Usage: python scripts/build_instruments.py     (stdout <= 45 lines)
 - input_samples/<InstrumentName>/*.wav present -> build from those; otherwise synthesize 3 sets.
"""
import hashlib, io, math, os, random, re, struct, sys, wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import dwp_lib as L

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REF = os.path.join(ROOT, "workspace", "samples_ref")
IN = os.path.join(ROOT, "input_samples")
OUT = os.path.join(ROOT, "dist", "instruments")
SR = 44100
NOTE = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
log = []


def note_name(m):  # C4 = 60
    return "%s%d" % (NAMES[m % 12], m // 12 - 1)


# ---------------------------------------------------------------- FLAC (verbatim subframes, valid stream)
def _crc_table(poly, bits):
    top, mask = 1 << (bits - 1), (1 << bits) - 1
    t = []
    for i in range(256):
        c = i << (bits - 8)
        for _ in range(8):
            c = ((c << 1) ^ poly) & mask if c & top else (c << 1) & mask
        t.append(c)
    return t


C8, C16 = _crc_table(0x07, 8), _crc_table(0x8005, 16)


def crc8(b):
    c = 0
    for x in b: c = C8[c ^ x]
    return c


def crc16(b):
    c = 0
    for x in b: c = ((c << 8) & 0xFFFF) ^ C16[(c >> 8) ^ x]
    return c


def utf8_num(n):
    if n < 0x80: return bytes([n])
    if n < 0x800: return bytes([0xC0 | n >> 6, 0x80 | n & 63])
    if n < 0x10000: return bytes([0xE0 | n >> 12, 0x80 | n >> 6 & 63, 0x80 | n & 63])
    return bytes([0xF0 | n >> 18, 0x80 | n >> 12 & 63, 0x80 | n >> 6 & 63, 0x80 | n & 63])


def flac_encode(chans, rate=SR):
    """chans: list of lists of int16. Returns FLAC bytes."""
    nch, n = len(chans), len(chans[0])
    BS = 4096
    pcm = bytearray()
    for i in range(n):
        for c in chans: pcm += struct.pack("<h", c[i])
    md5 = hashlib.md5(bytes(pcm)).digest()
    frames = bytearray(); minf, maxf = 1 << 30, 0
    for fi, s in enumerate(range(0, n, BS)):
        cnt = min(BS, n - s)
        h = bytearray([0xFF, 0xF8, ((12 if cnt == BS else 7) << 4) | 9, ((nch - 1) << 4) | 0x08])
        h += utf8_num(fi)
        if cnt != BS: h += struct.pack(">H", cnt - 1)
        h.append(crc8(bytes(h)))
        f = bytearray(h)
        for c in chans:
            f.append(0x02)  # verbatim subframe, no wasted bits
            f += struct.pack(">%dh" % cnt, *c[s:s + cnt])
        f += struct.pack(">H", crc16(bytes(f)))
        minf, maxf = min(minf, len(f)), max(maxf, len(f))
        frames += f
    si = struct.pack(">HH", BS, BS) + minf.to_bytes(3, "big") + maxf.to_bytes(3, "big")
    si += ((rate << 44) | ((nch - 1) << 41) | (15 << 36) | n).to_bytes(8, "big") + md5
    return b"fLaC" + bytes([0x80, 0, 0, 34]) + si + bytes(frames)


def flac_verify(data, chans):
    """Re-parse own stream: check magic, STREAMINFO, every frame CRC8/CRC16, and decoded samples."""
    assert data[:4] == b"fLaC" and data[4] == 0x80
    p, got, nch = 42, [[] for _ in chans], len(chans)
    while p < len(data):
        q = p
        assert data[q] == 0xFF and data[q + 1] == 0xF8
        bsc = data[q + 2] >> 4; q += 4
        lead = data[q]; q += 1 if lead < 0x80 else 2 if lead < 0xE0 else 3 if lead < 0xF0 else 4  # utf8 frame no.
        if bsc == 7: cnt = struct.unpack(">H", data[q:q + 2])[0] + 1; q += 2
        else: cnt = 4096
        assert crc8(data[p:q]) == data[q]; q += 1
        for ch in range(nch):
            assert data[q] == 0x02; q += 1
            got[ch] += struct.unpack(">%dh" % cnt, data[q:q + 2 * cnt]); q += 2 * cnt
        assert crc16(data[p:q]) == struct.unpack(">H", data[q:q + 2])[0]; q += 2
        p = q
    assert got == [list(c) for c in chans], "sample mismatch"


# ---------------------------------------------------------------- synthesis
def to_i16(x):
    pk = max(1e-9, max(abs(v) for v in x))
    g = 0.89 / pk
    return [int(max(-32767, min(32767, round(v * g * 32767)))) for v in x]


def synth_pluck(f, dur=2.6):
    n = int(SR * dur); N = max(2, int(SR / f))
    rnd = random.Random(int(f * 100))
    buf = [rnd.uniform(-1, 1) for _ in range(N)]
    for i in range(1, N): buf[i] = 0.5 * buf[i] + 0.5 * buf[i - 1]  # softer excitation (dark)
    out, prev, lp = [], 0.0, 0.0
    dec = 0.9965 if f < 200 else 0.994
    i = 0
    for k in range(n):
        a = buf[i]; b = buf[(i + 1) % N]
        v = dec * 0.5 * (a + b)
        buf[i] = v
        i = (i + 1) % N
        lp += 0.45 * (v - lp)  # soft low-pass
        out.append(lp)
    fade = int(SR * 0.3)
    for k in range(fade): out[n - fade + k] *= 1 - k / fade
    return out


def synth_808(f, dur=1.6):
    n = int(SR * dur); ph = 0.0; out = []
    for k in range(n):
        t = k / SR
        fr = f * (1 + 2.2 * math.exp(-t / 0.035))  # pitch envelope on attack
        ph += 2 * math.pi * fr / SR
        amp = (1 - math.exp(-t / 0.002)) * math.exp(-t / 0.6)
        x = math.sin(ph) * amp * 1.6
        out.append(math.tanh(x) + 0.08 * math.tanh(3 * x) ** 3)  # soft clip + light odd harmonics
    fade = int(SR * 0.15)
    for k in range(fade): out[n - fade + k] *= 1 - k / fade
    return out


def synth_keys(f, dur=2.4):
    n = int(SR * dur); out = []; lp = 0.0
    rnd = random.Random(int(f))
    ph_wob = rnd.uniform(0, 6.28)
    cut = 0.28 if f < 400 else 0.2  # one-pole LP coefficient (~2-3 kHz): rolls off highs
    pc = pm = 0.0
    for k in range(n):
        t = k / SR
        wob = 1 + 0.0035 * math.sin(2 * math.pi * 0.55 * t + ph_wob) + 0.0015 * math.sin(2 * math.pi * 5.1 * t)  # tape detune
        fc = f * wob
        pm += 2 * math.pi * fc * 1.0 / SR  # modulator ratio 1 (tine/body)
        idx = 0.9 + 2.6 * math.exp(-t / 0.18)
        pc += 2 * math.pi * fc / SR
        car = math.sin(pc + idx * math.sin(pm))
        tine = 0.18 * math.sin(2 * math.pi * fc * 14 * t + 0.5) * math.exp(-t / 0.035)
        amp = (1 - math.exp(-t / 0.003)) * (0.55 * math.exp(-t / 1.1) + 0.45 * math.exp(-t / 0.28))
        lp += cut * ((car + tine) * amp - lp)
        out.append(lp)
    fade = int(SR * 0.25)
    for k in range(fade): out[n - fade + k] *= 1 - k / fade
    return out


SYNTH = {  # name -> (category folder, donor file, generator)
    "Custom_Dark_Pluck": ("Guitar", "Purity Guitar.dwp", synth_pluck),
    "Custom_Sub_808": ("Synth Bass", "Ogun Clockwork.dwp", synth_808),
    "Custom_LoFi_Keys": ("Keyboard", "Morphine Clavinet.dwp", synth_keys),
}


# ---------------------------------------------------------------- user samples
def root_from_name(fn):
    b = os.path.splitext(os.path.basename(fn))[0]
    m = re.search(r"(?<![A-Za-z])([A-Ga-g])([#b]?)(-?\d)(?!\d)", b)
    if m:
        pc = NOTE[m.group(1).upper()] + {"#": 1, "b": -1, "": 0}[m.group(2)]
        return 12 * (int(m.group(3)) + 1) + pc
    m = re.search(r"(?<!\d)(\d{1,3})(?!\d)", b)
    if m and int(m.group(1)) <= 127: return int(m.group(1))
    return None


def root_from_pitch(x, rate):
    seg = x[int(rate * 0.1):int(rate * 0.1) + 4096] or x[:4096]
    best, bl = -1e30, None
    for lag in range(int(rate / 1500), min(len(seg) // 2, int(rate / 30))):
        s = sum(seg[i] * seg[i + lag] for i in range(0, len(seg) - lag, 2))
        if s > best: best, bl = s, lag
    return int(round(69 + 12 * math.log2(rate / bl / 440))) if bl else 60


def read_wav(path):
    with wave.open(path) as w:
        nch, sw, rate, nf = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(nf)
    if sw == 1: v = [(b - 128) << 8 for b in raw]
    elif sw == 2: v = list(struct.unpack("<%dh" % (len(raw) // 2), raw))
    elif sw == 3: v = [int.from_bytes(raw[i:i + 3], "little", signed=True) >> 8 for i in range(0, len(raw), 3)]
    else: raise ValueError("unsupported sample width %d" % sw)
    return [v[c::nch] for c in range(min(nch, 2))], rate


def zones_layout(roots):
    """Gapless key ranges 0..127: split at midpoints between neighbouring roots."""
    rs = sorted(roots); res = {}
    for i, r in enumerate(rs):
        low = 0 if i == 0 else res[rs[i - 1]][1] + 1
        high = 127 if i == len(rs) - 1 else r + (rs[i + 1] - r) // 2
        res[r] = (low, high)
    return res


# ---------------------------------------------------------------- build
def build_one(name, cat, donor_file, samples):
    """samples: list of dict(file, root, chans, rate)."""
    donor = open(os.path.join(REF, donor_file), "rb").read()
    lay = zones_layout([s["root"] for s in samples])
    base = os.path.join(OUT, cat, name)
    os.makedirs(base, exist_ok=True)
    zs = []
    for s in sorted(samples, key=lambda s: s["root"]):
        data = flac_encode(s["chans"], s["rate"])
        flac_verify(data, s["chans"])
        open(os.path.join(base, s["file"]), "wb").write(data)
        fr = len(s["chans"][0]); lo, hi = lay[s["root"]]
        blk = 1
        while blk * 2 <= max(4, fr // 4096): blk *= 2
        zs.append(dict(name=os.path.splitext(s["file"])[0],
                       path="%%ILSharedData%%\\DirectWave\\Custom\\%s\\%s" % (name, s["file"]),
                       root=s["root"], low=lo, high=hi, lovel=0, hivel=127, frames=fr,
                       channels=len(s["chans"]), blk=blk, rate=s["rate"], loop=None))
    dwp = L.build(donor, name, "C:\\Users\\Arlo\\Documents\\Image-Line\\Data\\DirectWave\\%s.dwph" % name, zs)
    S = L.parse(dwp)  # self-check: re-parse, tiling, counts
    assert S["num_zones"] == len(zs) == len(S["zones"])
    for z, k in zip(zs, S["zones"]):
        kb = dict(k)[L.Z_KEY]
        assert (kb[0], kb[1], kb[2], kb[3], kb[4]) == (z["root"], z["low"], z["high"], 0, 127)
    open(os.path.join(OUT, cat, name + ".dwp"), "wb").write(dwp)
    log.append("%-18s %-11s donor=%-18s zones=%2d dwp=%6d B  keys %s..%s" % (
        name, cat, donor_file[:-4], len(zs), len(dwp), note_name(zs[0]["root"]), note_name(zs[-1]["root"])))


def main():
    user = [d for d in sorted(os.listdir(IN)) if os.path.isdir(os.path.join(IN, d))
            and any(f.lower().endswith(".wav") for f in os.listdir(os.path.join(IN, d)))] if os.path.isdir(IN) else []
    if user:
        log.append("input_samples: %s" % user)
        donors = list(SYNTH.values())
        for i, d in enumerate(user):
            cat, donor, _ = donors[i % 3]
            smp, seen = [], set()
            for fn in sorted(os.listdir(os.path.join(IN, d))):
                if not fn.lower().endswith(".wav"): continue
                chans, rate = read_wav(os.path.join(IN, d, fn))
                r = root_from_name(fn)
                if r is None: r = root_from_pitch(chans[0], rate)
                if r in seen: continue
                seen.add(r)
                smp.append(dict(file=re.sub(r"[^\w#. -]", "_", fn), root=r, chans=chans, rate=rate))
            build_one(d, cat, donor, smp)
    else:
        log.append("input_samples/ empty -> synthesizing 3 sets (12 notes, C2..C6)")
        midis = [round(36 + i * 48 / 11) for i in range(12)]
        for name, (cat, donor, gen) in SYNTH.items():
            smp = []
            for m in midis:
                f = 440.0 * 2 ** ((m - 69) / 12)
                smp.append(dict(file="%s_%s.wav" % (name, note_name(m)), root=m, chans=[to_i16(gen(f))], rate=SR))
            build_one(name, cat, donor, smp)
    tot = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(OUT) for f in fs)
    log.append("Output: %s  (%.1f MB). FLAC CRC8/CRC16 + sample round-trip verified; .dwp re-parsed OK" % (OUT, tot / 1e6))
    print("\n".join(log[:45]))


main()
