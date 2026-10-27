"""Stage 1.6 Step 6: Wi-Fi UI Telemetry Receiver Server (0.0.0.0:8765/snap).
Prints local LAN IP & port 8765 on startup, receives PNG + view hierarchy JSON from iPhone,
saves into workspace/ui_snapshots/, and prints an instant layout & 44pt hit-area audit report.
Pure Python stdlib only.
"""
import base64
import json
import os
import socket
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(ROOT, "workspace", "ui_snapshots")
PORT = 8765


def get_local_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def analyze_telemetry_payload(payload):
    views = payload.get("views", [])
    screen = payload.get("screen", [844, 390])
    safe_insets = payload.get("safeAreaInsets", [0.0, 0.0, 0.0, 0.0])  # top, left, bottom, right
    safe_left = safe_insets[1] if len(safe_insets) >= 2 else 0.0
    safe_right = screen[0] - (safe_insets[3] if len(safe_insets) >= 4 else 0.0)
    issues = []
    for v in views:
        v_id = v.get("id") or v.get("text") or v.get("class", "UIView")
        sf = v.get("screenFrame", [0, 0, 0, 0])
        if v.get("isClipped"):
            issues.append(f"[Clipped] {v_id} frame={v.get('frame')}")
        if v.get("touchTargetTooSmall"):
            issues.append(f"[HitArea<44pt] {v_id} hitFrame={v.get('hitFrame', v.get('frame'))}")
        if v.get("overlapsSibling"):
            issues.append(f"[HitAreaOverlap] {v_id} hitFrame={v.get('hitFrame', v.get('frame'))}")
        if v.get("id") == "floatingDSPButton" and (sf[0] < safe_left or sf[0] + sf[2] > safe_right):
            issues.append(f"[SafeAreaViolation] {v_id} screenFrame={sf} vs safeArea={safe_insets}")
    return {
        "device": payload.get("device", "iOS"),
        "screen": screen,
        "safeAreaInsets": safe_insets,
        "views_inspected": len(views),
        "issues_count": len(issues),
        "issues": issues,
    }


class TelemetryHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_POST(self):
        if self.path != "/snap":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body.decode("utf-8"))
        except Exception as exc:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(exc).encode("utf-8"))
            return

        os.makedirs(SNAP_DIR, exist_ok=True)
        ts = int(payload.get("timestamp") or time.time())
        png_b64 = payload.get("png_base64", "")
        png_bytes = base64.b64decode(png_b64) if png_b64 else b""

        png_path = os.path.join(SNAP_DIR, f"snap_{ts}.png")
        json_path = os.path.join(SNAP_DIR, f"snap_{ts}.json")
        if png_bytes:
            with open(png_path, "wb") as f:
                f.write(png_bytes)
            with open(os.path.join(SNAP_DIR, "latest.png"), "wb") as f:
                f.write(png_bytes)

        audit = analyze_telemetry_payload(payload)
        meta = dict(payload)
        meta.pop("png_base64", None)
        meta["audit"] = audit
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        print(f"[UI-Snap] Device={audit['device']} Screen={audit['screen']} Safe={audit['safeAreaInsets']} Views={audit['views_inspected']} -> {png_path}")
        if audit["issues"]:
            print(f"  WARN: {audit['issues_count']} layout defect(s) detected:")
            for item in audit["issues"][:15]:
                print("   *", item)
        else:
            print("  OK: 0 layout defects (all hit-areas >= 44pt, 0 overlaps, 0 safe-area violations)")

        resp_bytes = json.dumps({"status": "ok", "audit": audit}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp_bytes)))
        self.end_headers()
        self.wfile.write(resp_bytes)


def run_self_test():
    lan_ip = get_local_lan_ip()
    print(f"Telemetry Receiver Self-Test | Local LAN Endpoint: http://{lan_ip}:{PORT}/snap")
    server = HTTPServer(("127.0.0.1", PORT), TelemetryHandler)
    t = threading.Thread(target=server.handle_request, daemon=True)
    t.start()

    preview_png = os.path.join(ROOT, "workspace", "ui_preview_stage1.png")
    png_b64 = base64.b64encode(open(preview_png, "rb").read()).decode("ascii") if os.path.isfile(preview_png) else ""
    sample_payload = {
        "device": "iPhone15,2 (SelfTest)",
        "screen": [852, 393],
        "safeAreaInsets": [0.0, 59.0, 21.0, 0.0],
        "timestamp": int(time.time()),
        "views": [
            {"class": "FLMHitButton", "id": "floatingDSPButton", "text": "DSP", "frame": [71, 56, 44, 44], "hitFrame": [71, 56, 44, 44], "screenFrame": [71, 56, 44, 44], "isClipped": False, "touchTargetTooSmall": False, "overlapsSibling": False},
            {"class": "UIView", "id": "mainDSPPanel", "text": "", "frame": [166, 28, 520, 336], "hitFrame": [166, 28, 520, 336], "screenFrame": [166, 28, 520, 336], "isClipped": False, "touchTargetTooSmall": False, "overlapsSibling": False},
        ],
        "png_base64": png_b64,
    }
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/snap",
        data=json.dumps(sample_payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    server.server_close()
    print(f"[Self-Test] HTTP 200 OK -> status={res['status']}, issues={res['audit']['issues_count']}")


def main():
    if "--self-test" in sys.argv:
        run_self_test()
        return
    lan_ip = get_local_lan_ip()
    print(f"UI Telemetry Receiver listening on http://{lan_ip}:{PORT}/snap (bind 0.0.0.0:{PORT}) -> {SNAP_DIR}")
    HTTPServer(("0.0.0.0", PORT), TelemetryHandler).serve_forever()


if __name__ == "__main__":
    main()
