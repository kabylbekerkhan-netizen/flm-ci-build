"""DwPr (DirectWave Program) container helpers. Stdlib only.

Layout (little-endian), reverse-engineered in phase 1.5:
  0x00  'DwPr'
  0x04  u32 version (0x25)
  0x08..0x23  misc header
  0x24  u32 =1
  0x28  u64 payload_len  (= file_size - 0x30)
  0x30  42 bytes fixed header block; u32 num_zones at 0x4A
  0x5A  tag stream, every record = [u32 tag][u64 len][len bytes]
        0x66 name, 0x67 dwph path, 0x68..0x6E program params,
        0x03 zone container (children = same record format, ends with 0x04 len 0),
        0x02 end-of-program (len 0)
  zone children: 0x1F4 keyzone(25 B: root,low,high,lovel,hivel,...),
                 0x1F5 sample name, 0x1F6 sample path, 0x1F7 sample info(40 B)
"""
import struct

HDR_LEN = 0x30
FIXED_END = 0x5A
OFF_PAYLOAD = 0x28
OFF_NUMZONES = 0x4A
T_NAME, T_PATH, T_ZONE, T_END = 0x66, 0x67, 0x03, 0x02
Z_KEY, Z_NAME, Z_PATH, Z_INFO = 0x1F4, 0x1F5, 0x1F6, 0x1F7


def walk(d, start, end):
    """Yield (offset, tag, data) for records in d[start:end]; raises if not tiled exactly."""
    p = start
    while p < end:
        tag, ln = struct.unpack_from("<IQ", d, p)
        if p + 12 + ln > end:
            raise ValueError("record overruns at 0x%x" % p)
        yield p, tag, d[p + 12:p + 12 + ln]
        p += 12 + ln
    if p != end:
        raise ValueError("stream does not tile")


def rec(tag, data):
    return struct.pack("<IQ", tag, len(data)) + data


def parse(d):
    if d[:4] != b"DwPr":
        raise ValueError("bad magic")
    top = list(walk(d, FIXED_END, len(d)))
    zones = [[(t2, c2) for _, t2, c2 in walk(c, 0, len(c))] for _, t, c in top if t == T_ZONE]
    return {"head": d[:FIXED_END], "top": [(t, c) for _, t, c in top], "zones": zones,
            "num_zones": struct.unpack_from("<I", d, OFF_NUMZONES)[0]}


def build(donor, name, path, zones):
    """donor: bytes of factory .dwp. zones: list of dicts(name,path,root,low,high,lovel,hivel,frames,
    loop(start,end)|None). Zone template = first zone of donor."""
    P = parse(donor)
    zt = P["zones"][0]
    head = bytearray(P["head"])
    struct.pack_into("<I", head, OFF_NUMZONES, len(zones))
    body = bytearray()
    for t, c in P["top"]:
        if t == T_NAME:
            body += rec(t, name.encode())
        elif t == T_PATH:
            body += rec(t, path.encode())
        elif t == T_ZONE:
            continue
        elif t == T_END:
            for z in zones:
                kids = bytearray()
                for ct, cd in zt:
                    cd = bytearray(cd)
                    if ct == Z_KEY:
                        cd[0], cd[1], cd[2], cd[3], cd[4] = z["root"], z["low"], z["high"], z["lovel"], z["hivel"]
                    elif ct == Z_NAME:
                        cd = z["name"].encode()
                    elif ct == Z_PATH:
                        cd = z["path"].encode()
                    elif ct == Z_INFO:
                        # u64 frames | u32 | u32 | f32 rate | u32 | u32 loop_start | u32 loop_end | u32 | u32
                        struct.pack_into("<Q", cd, 0, z["frames"])
                        struct.pack_into("<I", cd, 8, z.get("channels", 1))
                        struct.pack_into("<I", cd, 12, z.get("blk", 16))
                        struct.pack_into("<f", cd, 16, float(z["rate"]))
                        ls, le = z.get("loop") or (0, 0)
                        struct.pack_into("<I", cd, 20, 2 if ls < le else 0)  # loop mode
                        struct.pack_into("<II", cd, 24, ls, le)
                    kids += rec(ct, bytes(cd))
                body += rec(T_ZONE, bytes(kids))
            body += rec(t, c)
        else:
            body += rec(t, c)
    struct.pack_into("<Q", head, OFF_PAYLOAD, len(body) + (FIXED_END - HDR_LEN))
    return bytes(head) + bytes(body)
