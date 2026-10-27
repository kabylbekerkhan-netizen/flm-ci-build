"""Stage 1.6 Step 5: Multi-Profile Geometry & Hit-Area (44pt) Auditor + Pure-Python Vision Renderer.
Audits 4 iPhone Landscape profiles (844x390, 852x393, 874x402, 932x430) in both LandscapeLeft & LandscapeRight
(safeAreaInsets on left vs right), verifies 44x44pt expanded hit-areas via pointInside:withEvent: with zero
hit-area overlap between neighbors, and renders workspace/ui_preview_stage1.png.
Strictly pure Python stdlib, stdout <= 40 lines.
"""
import json
import math
import os
import re
import struct
import zlib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OVERLAY_MM = os.path.join(ROOT, "plugin_src", "ui", "FloatingOverlay.mm")
OUT_PNG = os.path.join(ROOT, "workspace", "ui_preview_stage1.png")
OUT_JSON = os.path.join(ROOT, "workspace", "ui_audit_report.json")

MIN_HIT_SIZE = 44.0

# Profiles: (name, width, height, notch_inset, home_bottom_inset)
DEVICE_PROFILES = [
    ("iPhone 13/14 (844x390)",       844, 390, 47.0, 21.0),
    ("iPhone 14 Pro/15 (852x393)",   852, 393, 59.0, 21.0),
    ("iPhone 16 Pro (874x402)",      874, 402, 62.0, 21.0),
    ("iPhone 15/16 ProMax (932x430)",932, 430, 59.0, 21.0),
]

FONT5X7 = {
    " ": [0,0,0,0,0,0,0],
    "A": [0x0E,0x11,0x11,0x1F,0x11,0x11,0x11], "B": [0x1E,0x11,0x11,0x1E,0x11,0x11,0x1E],
    "C": [0x0E,0x11,0x10,0x10,0x10,0x11,0x0E], "D": [0x1C,0x12,0x11,0x11,0x11,0x12,0x1C],
    "E": [0x1F,0x10,0x10,0x1E,0x10,0x10,0x1F], "F": [0x1F,0x10,0x10,0x1E,0x10,0x10,0x10],
    "G": [0x0E,0x11,0x10,0x17,0x11,0x11,0x0F], "H": [0x11,0x11,0x11,0x1F,0x11,0x11,0x11],
    "I": [0x0E,0x04,0x04,0x04,0x04,0x04,0x0E], "J": [0x07,0x02,0x02,0x02,0x02,0x12,0x0C],
    "K": [0x11,0x12,0x14,0x18,0x14,0x12,0x11], "L": [0x10,0x10,0x10,0x10,0x10,0x10,0x1F],
    "M": [0x11,0x1B,0x15,0x15,0x11,0x11,0x11], "N": [0x11,0x19,0x15,0x13,0x11,0x11,0x11],
    "O": [0x0E,0x11,0x11,0x11,0x11,0x11,0x0E], "P": [0x1E,0x11,0x11,0x1E,0x10,0x10,0x10],
    "Q": [0x0E,0x11,0x11,0x11,0x15,0x12,0x0D], "R": [0x1E,0x11,0x11,0x1E,0x14,0x12,0x11],
    "S": [0x0F,0x10,0x10,0x0E,0x01,0x01,0x1E], "T": [0x1F,0x04,0x04,0x04,0x04,0x04,0x04],
    "U": [0x11,0x11,0x11,0x11,0x11,0x11,0x0E], "V": [0x11,0x11,0x11,0x11,0x11,0x0A,0x04],
    "W": [0x11,0x11,0x11,0x15,0x15,0x1B,0x11], "X": [0x11,0x11,0x0A,0x04,0x0A,0x11,0x11],
    "Y": [0x11,0x11,0x0A,0x04,0x04,0x04,0x04], "Z": [0x1F,0x01,0x02,0x04,0x08,0x10,0x1F],
    "0": [0x0E,0x11,0x13,0x15,0x19,0x11,0x0E], "1": [0x04,0x0C,0x04,0x04,0x04,0x04,0x0E],
    "2": [0x0E,0x11,0x01,0x06,0x08,0x10,0x1F], "3": [0x1F,0x02,0x04,0x06,0x01,0x11,0x0E],
    "4": [0x02,0x06,0x0A,0x12,0x1F,0x02,0x02], "5": [0x1F,0x10,0x1E,0x01,0x01,0x11,0x0E],
    "6": [0x06,0x08,0x10,0x1E,0x11,0x11,0x0E], "7": [0x1F,0x01,0x02,0x04,0x08,0x08,0x08],
    "8": [0x0E,0x11,0x11,0x0E,0x11,0x11,0x0E], "9": [0x0E,0x11,0x11,0x0F,0x01,0x02,0x0C],
    ".": [0x00,0x00,0x00,0x00,0x00,0x0C,0x0C], ":": [0x00,0x0C,0x0C,0x00,0x0C,0x0C,0x00],
    "-": [0x00,0x00,0x00,0x1F,0x00,0x00,0x00], "/": [0x01,0x02,0x02,0x04,0x08,0x08,0x10],
    "(": [0x02,0x04,0x08,0x08,0x08,0x04,0x02], ")": [0x08,0x04,0x02,0x02,0x02,0x04,0x08],
    "<": [0x02,0x04,0x08,0x10,0x08,0x04,0x02], "%": [0x19,0x19,0x02,0x04,0x08,0x13,0x13],
    "|": [0x04,0x04,0x04,0x04,0x04,0x04,0x04], "=": [0x00,0x00,0x1F,0x00,0x1F,0x00,0x00],
    "d": [0x01,0x01,0x0D,0x13,0x11,0x13,0x0D], "z": [0x00,0x00,0x1F,0x02,0x04,0x08,0x1F],
}


class Canvas:
    def __init__(self, w, h, bg=(12, 12, 15)):
        self.w, self.h = w, h
        self.buf = bytearray(bg) * (w * h)

    def set_px(self, x, y, col, alpha=1.0):
        if 0 <= x < self.w and 0 <= y < self.h:
            idx = (y * self.w + x) * 3
            if alpha >= 0.999:
                self.buf[idx:idx+3] = bytes(col)
            else:
                inv = 1.0 - alpha
                self.buf[idx]   = int(self.buf[idx]   * inv + col[0] * alpha)
                self.buf[idx+1] = int(self.buf[idx+1] * inv + col[1] * alpha)
                self.buf[idx+2] = int(self.buf[idx+2] * inv + col[2] * alpha)

    def fill_rect(self, x, y, w, h, col, r=0, alpha=1.0):
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        rad = int(round(r))
        for py in range(max(0, y0), min(self.h, y1)):
            for px in range(max(0, x0), min(self.w, x1)):
                if rad > 0:
                    dx = max(x0 + rad - px, px - (x1 - 1 - rad), 0)
                    dy = max(y0 + rad - py, py - (y1 - 1 - rad), 0)
                    if dx * dx + dy * dy > rad * rad:
                        continue
                self.set_px(px, py, col, alpha)

    def stroke_rect(self, x, y, w, h, col, r=0, thickness=1, alpha=1.0):
        x0, y0 = int(round(x)), int(round(y))
        x1, y1 = int(round(x + w)), int(round(y + h))
        rad = int(round(r))
        t = max(1, int(round(thickness)))
        for py in range(max(0, y0), min(self.h, y1)):
            for px in range(max(0, x0), min(self.w, x1)):
                dx_out = max(x0 + rad - px, px - (x1 - 1 - rad), 0)
                dy_out = max(y0 + rad - py, py - (y1 - 1 - rad), 0)
                d2 = dx_out * dx_out + dy_out * dy_out
                if rad > 0 and d2 > rad * rad:
                    continue
                in_edge = (
                    px < x0 + t or px >= x1 - t or py < y0 + t or py >= y1 - t
                    or (rad > 0 and d2 >= (max(0, rad - t)) ** 2)
                )
                if in_edge:
                    self.set_px(px, py, col, alpha)

    def draw_line(self, x0, y0, x1, y1, col, thickness=1, dashed=False, alpha=1.0):
        steps = int(max(abs(x1 - x0), abs(y1 - y0), 1) * 2)
        half = max(0, int((thickness - 1) // 2))
        for s in range(steps + 1):
            if dashed and (s // 8) % 2 == 1:
                continue
            px = int(round(x0 + (x1 - x0) * s / steps))
            py = int(round(y0 + (y1 - y0) * s / steps))
            for dy in range(-half, half + 1):
                for dx in range(-half, half + 1):
                    self.set_px(px + dx, py + dy, col, alpha)

    def draw_text(self, x, y, text, col, scale=1, align="left", box_w=0):
        char_w = 6 * scale
        total_w = len(text) * char_w - scale
        sx = int(round(x))
        if align == "center" and box_w > 0:
            sx = int(round(x + (box_w - total_w) * 0.5))
        elif align == "right" and box_w > 0:
            sx = int(round(x + box_w - total_w))
        sy = int(round(y))
        for ch in text:
            glyph = FONT5X7.get(ch) or FONT5X7.get(ch.upper()) or FONT5X7[" "]
            for row_idx, row_bits in enumerate(glyph):
                for col_idx in range(5):
                    if (row_bits >> (4 - col_idx)) & 1:
                        for dy in range(scale):
                            for dx in range(scale):
                                self.set_px(sx + col_idx * scale + dx, sy + row_idx * scale + dy, col)
            sx += char_w

    def save_png(self, path):
        raw = bytearray()
        stride = self.w * 3
        for y in range(self.h):
            raw.append(0)
            raw.extend(self.buf[y * stride : (y + 1) * stride])

        def chunk(tag, data):
            return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

        ihdr = struct.pack(">IIBBBBB", self.w, self.h, 8, 2, 0, 0, 0)
        png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b"")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(png)


def expand_hit_rect(rect, has_point_inside_expansion=True):
    """Compute effective hit-area matching ExpandedHitBounds in FloatingOverlay.mm."""
    x, y, w, h = rect
    if not has_point_inside_expansion:
        return [x, y, w, h]
    dx = min(0.0, (w - MIN_HIT_SIZE) * 0.5)
    dy = min(0.0, (h - MIN_HIT_SIZE) * 0.5)
    return [x + dx, y + dy, w - 2.0 * dx, h - 2.0 * dy]


def clamp_center_rect(rect, screen_w, screen_h, safe_insets):
    """Simulate [FLMFloatingOverlay clampCenter:forSize:inWindow:] with safe_insets=(top,left,bottom,right)."""
    x, y, w, h = rect
    top, left, bottom, right = safe_insets
    cx, cy = x + w * 0.5, y + h * 0.5
    min_x = left + 8.0 + w * 0.5
    max_x = screen_w - right - 8.0 - w * 0.5
    min_y = top + 8.0 + h * 0.5
    max_y = screen_h - bottom - 8.0 - h * 0.5
    cx = max(min_x, min(max_x, cx))
    cy = max(min_y, min(max_y, cy))
    return [cx - w * 0.5, cy - h * 0.5, w, h]


def parse_objc_ui(mm_text):
    def find_float(pattern, default):
        m = re.search(pattern, mm_text)
        return float(m.group(1)) if m else default

    def find_rect(var_prefix, default):
        pat = rf"{var_prefix}[^\n]*?CGRectMake\(\s*([^,]+),\s*([^,]+),\s*([^,]+),\s*([^)]+)\)"
        m = re.search(pat, mm_text)
        if not m:
            return default
        return [m.group(1).strip(), m.group(2).strip(), m.group(3).strip(), m.group(4).strip()]

    has_hit_subclass = ("pointInside:" in mm_text and "ExpandedHitBounds" in mm_text)
    uses_safe_area = ("win.safeAreaInsets" in mm_text and "clampCenter:" in mm_text)

    pw = find_float(r"CGFloat\s+pw\s*=\s*([0-9.]+)", 520.0)
    ph = find_float(r"CGFloat\s+ph\s*=\s*([0-9.]+)", 336.0)
    env = {"pw": pw, "ph": ph, "cw": pw - 20.0, "startX": 68.0, "startY": 56.0}

    def eval_expr(expr, local_vars=None):
        ns = dict(env)
        if local_vars:
            ns.update(local_vars)
        return float(eval(expr, {"__builtins__": {}}, ns))

    def eval_rect(raw_list, local_vars=None):
        return [eval_expr(e, local_vars) for e in raw_list]

    btn_rect = eval_rect(find_rect(r"_floatingBtn\.frame\s*=", ["startX", "startY", "44", "44"]))
    hdr_rect = eval_rect(find_rect(r"UIView\*\s+header\s*=", ["10", "8", "pw - 20", "60"]))
    title_rect = eval_rect(find_rect(r"UILabel\*\s+titleLbl\s*=", ["8", "3", "132", "14"]))
    mode_rect = eval_rect(find_rect(r"_modeBtn\.frame\s*=", ["8", "20", "132", "32"]))
    wave_rect = eval_rect(find_rect(r"_waveformView\s*=", ["146", "4", "178", "36"]))
    diag_raw = find_rect(r"_diagLabel\s*=", None)
    diag_rect = eval_rect(diag_raw) if diag_raw else None
    snap_raw = find_rect(r"_snapBtn\.frame\s*=", None)
    snap_rect = eval_rect(snap_raw) if snap_raw else None
    byp_rect = eval_rect(find_rect(r"_bypassBtn\.frame\s*=", ["384", "8", "56", "32"]))
    close_rect = eval_rect(find_rect(r"closeBtn\.frame\s*=", ["446", "8", "46", "32"]))

    tab_y = find_float(r"tb\.frame\s*=\s*CGRectMake\([^,]+,\s*([0-9.]+)", 74.0)
    tab_h = find_float(r"tb\.frame\s*=\s*CGRectMake\([^,]+,\s*[^,]+,\s*tabW,\s*([0-9.]+)", 32.0)

    mod1_rect = eval_rect(find_rect(r"_mod1Container\s*=", ["10", "112", "pw - 20", "ph - 122"]))
    env["cw"] = mod1_rect[2]

    row_step = find_float(r"CGFloat\s+y\s*=\s*[0-9.]+\s*\+\s*i\s*\*\s*([0-9.]+)", 51.0)
    row_y0 = find_float(r"CGFloat\s+y\s*=\s*([0-9.]+)\s*\+\s*i", 8.0)
    sld_raw = find_rect(r"(?:FLMHitSlider|UISlider)\*\s+sld\s*=", ["14", "y + 16", "cw - 28", "32"])

    sliders = []
    for i in range(4):
        y_val = row_y0 + i * row_step
        sliders.append(eval_rect(sld_raw, {"y": y_val, "i": i}))

    return {
        "pw": pw,
        "ph": ph,
        "has_hit_subclass": has_hit_subclass,
        "uses_safe_area": uses_safe_area,
        "floating_btn": btn_rect,
        "header": hdr_rect,
        "title": title_rect,
        "mode_btn": mode_rect,
        "waveform": wave_rect,
        "diag_label": diag_rect,
        "snap_btn": snap_rect,
        "bypass_btn": byp_rect,
        "close_btn": close_rect,
        "tab_y": tab_y,
        "tab_h": tab_h,
        "mod1_box": mod1_rect,
        "row_y0": row_y0,
        "row_step": row_step,
        "sliders": sliders,
    }


def rects_overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return not (ax + aw <= bx + 0.5 or bx + bw <= ax + 0.5 or ay + ah <= by + 0.5 or by + bh <= ay + 0.5)


def audit_all_profiles(layout):
    issues = []
    profile_results = []
    exp = layout["has_hit_subclass"]

    if not layout["uses_safe_area"]:
        issues.append("DEFECT [SafeArea]: Missing dynamic win.safeAreaInsets clamping in FloatingOverlay.mm")
    if layout["diag_label"] is None:
        issues.append("DEFECT [Diagnostics]: Missing _diagLabel live status bar in header")

    # 1. Check across all 4 screen sizes x 2 Landscape orientations (notch left vs notch right)
    for prof_name, sw, sh, notch_in, bot_in in DEVICE_PROFILES:
        for orient, safe_insets in [
            ("LandscapeLeft (insetLeft)",  (0.0, notch_in, bot_in, 0.0)),
            ("LandscapeRight (insetRight)",(0.0, 0.0, bot_in, notch_in)),
        ]:
            start_x = max(safe_insets[1] + 12.0, 68.0)
            start_y = max(safe_insets[0] + 12.0, 56.0)
            fb = clamp_center_rect([start_x, start_y, 44.0, 44.0], sw, sh, safe_insets)
            panel = clamp_center_rect([(sw - layout["pw"]) * 0.5, (sh - layout["ph"]) * 0.5, layout["pw"], layout["ph"]], sw, sh, safe_insets)

            safe_left = safe_insets[1]
            safe_right = sw - safe_insets[3]
            safe_bottom = sh - safe_insets[2]

            ok_fb = (fb[0] >= safe_left and fb[0] + fb[2] <= safe_right and fb[1] + fb[3] <= safe_bottom)
            ok_panel = (panel[0] >= safe_left and panel[0] + panel[2] <= safe_right and panel[1] + panel[3] <= safe_bottom)
            if not ok_fb:
                issues.append(f"DEFECT [SafeArea]: FloatingBtn {fb} violates safe area on {prof_name} {orient}")
            if not ok_panel:
                issues.append(f"DEFECT [SafeArea]: MainPanel {panel} violates safe area on {prof_name} {orient}")
            profile_results.append({"profile": prof_name, "orientation": orient, "panel": panel, "floating_btn": fb, "ok": ok_fb and ok_panel})

    # 2. Check Hit-Area (>= 44x44pt) & Non-Overlapping Hit-Areas of interactive controls
    hdr_controls = [
        ("modeBtn", layout["mode_btn"]),
        ("snapBtn", layout["snap_btn"]),
        ("bypassBtn", layout["bypass_btn"]),
        ("closeBtn", layout["close_btn"]),
    ]
    hdr_hit_rects = []
    for name, rect in hdr_controls:
        if not rect:
            issues.append(f"DEFECT [Missing]: Control '{name}' missing")
            continue
        hr = expand_hit_rect(rect, exp)
        if hr[2] < MIN_HIT_SIZE - 0.1 or hr[3] < MIN_HIT_SIZE - 0.1:
            issues.append(f"DEFECT [HitArea<44pt]: Header '{name}' hit-area={hr[2]:.1f}x{hr[3]:.1f}pt (< 44x44pt)")
        hdr_hit_rects.append((name, hr))

    for i in range(len(hdr_hit_rects)):
        for j in range(i + 1, len(hdr_hit_rects)):
            n1, h1 = hdr_hit_rects[i]
            n2, h2 = hdr_hit_rects[j]
            if rects_overlap(h1, h2):
                issues.append(f"DEFECT [HitAreaOverlap]: Header '{n1}' hit-area {h1} overlaps '{n2}' hit-area {h2}")

    # 3. Check 5 Tab buttons hit-areas (in panel coords)
    tab_w = (layout["pw"] - 20.0 - 16.0) / 5.0
    tab_hits = []
    for i in range(5):
        tr = [10.0 + i * (tab_w + 4.0), layout["tab_y"], tab_w, layout["tab_h"]]
        hr = expand_hit_rect(tr, exp)
        if hr[2] < MIN_HIT_SIZE - 0.1 or hr[3] < MIN_HIT_SIZE - 0.1:
            issues.append(f"DEFECT [HitArea<44pt]: Tab[{i}] hit-area={hr[2]:.1f}x{hr[3]:.1f}pt (< 44x44pt)")
        tab_hits.append((f"Tab[{i}]", hr))

    for i in range(len(tab_hits) - 1):
        if rects_overlap(tab_hits[i][1], tab_hits[i + 1][1]):
            issues.append(f"DEFECT [HitAreaOverlap]: {tab_hits[i][0]} overlaps {tab_hits[i+1][0]}")

    # Check header controls vs tab buttons hit-areas in panel coordinates
    hx, hy, _, _ = layout["header"]
    for hname, hrect in hdr_hit_rects:
        hp = [hx + hrect[0], hy + hrect[1], hrect[2], hrect[3]]
        for tname, trect in tab_hits:
            if rects_overlap(hp, trect):
                issues.append(f"DEFECT [HitAreaOverlap]: Header '{hname}' {hp} overlaps '{tname}' {trect}")

    # 4. Check 4 Sliders hit-areas (44pt height) & mutual non-overlap
    sld_hits = []
    for idx, sld in enumerate(layout["sliders"]):
        hr = expand_hit_rect(sld, exp)
        if hr[3] < MIN_HIT_SIZE - 0.1:
            issues.append(f"DEFECT [HitArea<44pt]: Slider[{idx}] hit-area height={hr[3]:.1f}pt (< 44pt)")
        sld_hits.append((f"Slider[{idx}]", hr))

    for i in range(len(sld_hits) - 1):
        if rects_overlap(sld_hits[i][1], sld_hits[i + 1][1]):
            issues.append(f"DEFECT [HitAreaOverlap]: {sld_hits[i][0]} hit-area {sld_hits[i][1]} overlaps {sld_hits[i+1][0]} {sld_hits[i+1][1]}")

    return issues, profile_results


def render_preview(layout, path):
    sw, sh = 844, 390
    cv = Canvas(sw, sh, bg=(18, 19, 24))

    cv.fill_rect(0, 0, sw, 36, (28, 30, 36))
    cv.draw_text(74, 14, "FL STUDIO MOBILE 4.10.1 // STAGE 1.6 GEOMETRY PREVIEW", (120, 124, 136), scale=1)
    for row in range(6):
        ry = 44 + row * 54
        cv.fill_rect(64, ry, sw - 76, 46, (24, 26, 32))
        for bar in range(8):
            bx = 160 + bar * 82
            cv.fill_rect(bx, ry + 6, 76, 34, (35, 38, 46) if (row + bar) % 2 == 0 else (29, 31, 39), r=4)

    cv.fill_rect(12, 135, 34, 120, (4, 4, 4), r=17)
    cv.stroke_rect(12, 135, 34, 120, (60, 60, 68), r=17, thickness=1)

    fbx, fby, fbw, fbh = layout["floating_btn"]
    cv.fill_rect(fbx, fby, fbw, fbh, (8, 8, 8), r=fbw * 0.5, alpha=0.92)
    cv.stroke_rect(fbx, fby, fbw, fbh, (212, 212, 216), r=fbw * 0.5, thickness=1)
    cv.draw_text(fbx, fby + (fbh - 7) * 0.5, "DSP", (228, 228, 231), scale=1, align="center", box_w=fbw)
    cv.fill_rect(fbx + fbw - 13, fby + 5, 8, 8, (138, 18, 34), r=4)

    pw, ph = layout["pw"], layout["ph"]
    px, py = (sw - pw) * 0.5, (sh - ph) * 0.5
    cv.fill_rect(px, py, pw, ph, (8, 8, 8), r=14, alpha=0.97)
    cv.stroke_rect(px, py, pw, ph, (212, 212, 216), r=14, thickness=1, alpha=0.55)

    hx, hy, hw, hh = layout["header"]
    ahx, ahy = px + hx, py + hy
    cv.fill_rect(ahx, ahy, hw, hh, (18, 18, 20), r=8)

    tx, ty, _, _ = layout["title"]
    cv.draw_text(ahx + tx, ahy + ty + 2, "FLM // DSP RACK", (228, 228, 231), scale=1)

    mx, my, mw, mh = layout["mode_btn"]
    cv.fill_rect(ahx + mx, ahy + my, mw, mh, (107, 15, 26), r=6)
    cv.stroke_rect(ahx + mx, ahy + my, mw, mh, (212, 212, 216), r=6, thickness=1, alpha=0.8)
    cv.draw_text(ahx + mx, ahy + my + (mh - 7) * 0.5, "MODE: MASTER OUT", (228, 228, 231), scale=1, align="center", box_w=mw)

    wx, wy, ww, wh = layout["waveform"]
    awx, awy = ahx + wx, ahy + wy
    cv.fill_rect(awx, awy, ww, wh, (8, 8, 8), r=6)
    cv.stroke_rect(awx, awy, ww, wh, (107, 15, 26), r=6, thickness=1)
    mid_y = awy + wh * 0.5
    cv.draw_line(awx + 2, mid_y, awx + ww - 2, mid_y, (212, 212, 216), thickness=1, alpha=0.2)
    ceil_off = 0.78 * (wh * 0.45)
    cv.draw_line(awx + 4, mid_y - ceil_off, awx + ww - 4, mid_y - ceil_off, (138, 18, 34), thickness=1, dashed=True, alpha=0.8)
    cv.draw_line(awx + 4, mid_y + ceil_off, awx + ww - 4, mid_y + ceil_off, (138, 18, 34), thickness=1, dashed=True, alpha=0.8)

    pts = []
    for i in range(int(ww) - 6):
        t = i / float(ww) * 4.0 * math.pi
        raw = 0.95 * math.sin(t) + 0.55 * math.sin(0.5 * t) + 0.25 * math.cos(3.0 * t)
        clipped = max(-0.78, min(0.78, math.tanh(raw * 1.4)))
        pts.append((awx + 3 + i, mid_y - clipped * (wh * 0.45)))
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        cv.draw_line(x0, y0, x1, y1, (138, 18, 34), thickness=3, alpha=0.85)
        cv.draw_line(x0, y0, x1, y1, (228, 228, 231), thickness=1, alpha=0.98)

    if layout["diag_label"]:
        dx, dy, _, _ = layout["diag_label"]
        cv.draw_text(ahx + dx, ahy + dy + 3, "HOOK: OK | CB=128 | FRAMES=512 | SR=44100 | MASTER", (212, 212, 216), scale=1)

    for btn_rect, txt, bg_c, bd_c in [
        (layout["snap_btn"], "SNAP", (28, 28, 32), (212, 212, 216)),
        (layout["bypass_btn"], "ACTIVE", (138, 18, 34), (212, 212, 216)),
        (layout["close_btn"], "HIDE", (40, 40, 44), (212, 212, 216)),
    ]:
        if btn_rect:
            bx, by, bw, bh = btn_rect
            cv.fill_rect(ahx + bx, ahy + by, bw, bh, bg_c, r=6)
            cv.stroke_rect(ahx + bx, ahy + by, bw, bh, bd_c, r=6, thickness=1, alpha=0.8)
            cv.draw_text(ahx + bx, ahy + by + (bh - 7) * 0.5, txt, (228, 228, 231), scale=1, align="center", box_w=bw)

    tab_names = ["1. 808/CLIP", "2. VOCAL TUNE", "3. HALFTIME", "4. LO-FI/SPACE", "5. AUv3/REC"]
    tab_w = (pw - 20.0 - 16.0) / 5.0
    for i, tname in enumerate(tab_names):
        tx_i = px + 10.0 + i * (tab_w + 4.0)
        ty_i = py + layout["tab_y"]
        th_i = layout["tab_h"]
        bg_c = (138, 18, 34) if i == 0 else (18, 18, 20)
        bd_c = (228, 228, 231) if i == 0 else (90, 90, 98)
        cv.fill_rect(tx_i, ty_i, tab_w, th_i, bg_c, r=6)
        cv.stroke_rect(tx_i, ty_i, tab_w, th_i, bd_c, r=6, thickness=1)
        cv.draw_text(tx_i, ty_i + (th_i - 7) * 0.5, tname, (228, 228, 231), scale=1, align="center", box_w=tab_w)

    mx, my, mw, mh = layout["mod1_box"]
    amx, amy = px + mx, py + my
    cv.fill_rect(amx, amy, mw, mh, (18, 18, 20), r=10)
    cv.stroke_rect(amx, amy, mw, mh, (138, 18, 34), r=10, thickness=1, alpha=0.7)

    titles = [
        ("SUB-OCTAVE MIX (-12 ST / 90Hz)", "35 %", 0.35),
        ("ASYMMETRIC DIODE DRIVE", "40 %", 0.40),
        ("HARD CLIPPER CEILING (dB)", "-0.5 dB", (12.0 - 0.5) / 12.0),
        ("LOW-END MONO MAKER (< 120Hz)", "100 %", 1.00),
    ]
    for i, (lbl, val_str, norm) in enumerate(titles):
        ry = amy + layout["row_y0"] + i * layout["row_step"]
        cv.draw_text(amx + 14, ry + 2, lbl, (228, 228, 231), scale=1)
        cv.draw_text(amx + mw - 114, ry + 2, val_str, (212, 212, 216), scale=1, align="right", box_w=100)

        sx, sy, sw_s, sh_s = layout["sliders"][i]
        asx, asy = amx + sx, amy + sy
        track_y = asy + sh_s * 0.5 - 3
        fill_w = max(6.0, sw_s * norm)
        cv.fill_rect(asx, track_y, sw_s, 6, (48, 48, 54), r=3)
        cv.fill_rect(asx, track_y, fill_w, 6, (138, 18, 34), r=3)
        knob_x = asx + sw_s * norm - 8
        knob_y = asy + sh_s * 0.5 - 8
        cv.fill_rect(knob_x, knob_y, 16, 16, (228, 228, 231), r=8)
        cv.stroke_rect(knob_x, knob_y, 16, 16, (107, 15, 26), r=8, thickness=2)

    cv.save_png(path)


def main():
    mm_text = open(OVERLAY_MM, encoding="utf-8").read()
    layout = parse_objc_ui(mm_text)
    issues, profile_results = audit_all_profiles(layout)
    render_preview(layout, OUT_PNG)

    report = {
        "note": "Static geometry & 44pt hit-area math check (Level A); NOT a native UIKit render check (Level B/C).",
        "profiles_tested": len(profile_results),
        "profile_results": profile_results,
        "issues_count": len(issues),
        "issues": issues,
    }
    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Tested {len(profile_results)} device/orientation profiles (844x390, 852x393, 874x402, 932x430 x L/R)")
    print(f"pointInside:withEvent: 44pt hit-area active={layout['has_hit_subclass']} | safeAreaInsets clamp={layout['uses_safe_area']}")
    print(f"Static Geometry & Hit-Area Audit (Level A): {len(issues)} issue(s) found")
    for item in issues[:20]:
        print("  -", item)


if __name__ == "__main__":
    main()
