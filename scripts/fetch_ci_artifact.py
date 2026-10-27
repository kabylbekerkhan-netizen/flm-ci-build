import io
import json
import pathlib
import time
import urllib.request
import zipfile

REPO = "kabylbekerkhan-netizen/flm-ci-build"
BUILD_DIR = pathlib.Path(r"C:\Projects\build")
MCP_CFG = pathlib.Path(r"C:\Users\mczmv\.gemini\config\mcp_config.json")


def get_token() -> str:
    cfg = json.loads(MCP_CFG.read_text(encoding="utf-8"))
    env = cfg["mcpServers"]["github-mcp-server"]["env"]
    return list(env.values())[0]


def api_get(url: str, token: str):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "FLM-CI-Fetcher",
            "Accept": "application/vnd.github+json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


class NoAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return urllib.request.Request(newurl, headers={"User-Agent": "FLM-CI-Fetcher"})


def download_artifact_zip(url: str, token: str) -> bytes:
    opener = urllib.request.build_opener(NoAuthRedirect())
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "FLM-CI-Fetcher",
            "Accept": "application/vnd.github+json",
        },
    )
    with opener.open(req) as resp:
        return resp.read()


def main():
    token = get_token()
    runs = api_get(f"https://api.github.com/repos/{REPO}/actions/runs?per_page=5", token)
    wruns = runs.get("workflow_runs", [])
    if not wruns:
        print("[ERROR] No workflow runs found.")
        return 1
    run = wruns[0]
    run_id = run["id"]
    print(f"[CI] Tracking run {run_id}: {run['html_url']}")

    dylib_downloaded = False
    for attempt in range(90):
        jobs_data = api_get(
            f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/jobs", token
        )
        jobs = jobs_data.get("jobs", [])
        summary = []
        job1_done = False
        job1_conclusion = None
        all_done = True
        for j in jobs:
            jname = j["name"]
            jstat = j["status"]
            jconc = j["conclusion"]
            summary.append(f"{jname}: {jstat} ({jconc})")
            if "Job 1" in jname and jstat == "completed":
                job1_done = True
                job1_conclusion = jconc
            if jstat != "completed":
                all_done = False

        if attempt % 3 == 0 or job1_done or all_done:
            print(f"[{attempt*5}s] " + " | ".join(summary), flush=True)

        if job1_done and not dylib_downloaded:
            if job1_conclusion != "success":
                print(f"[ERROR] Job 1 failed with conclusion: {job1_conclusion}")
                for j in jobs:
                    if "Job 1" in j["name"]:
                        for s in j.get("steps", []):
                            print(f"  Step {s['number']} {s['name']}: {s['conclusion']}")
                return 2
            arts = api_get(
                f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts",
                token,
            ).get("artifacts", [])
            for a in arts:
                if a["name"] == "FLM_CustomDSP_Bundle":
                    print(f"[CI] Downloading artifact {a['name']} ({a['size_in_bytes']} bytes)...")
                    zbytes = download_artifact_zip(a["archive_download_url"], token)
                    BUILD_DIR.mkdir(parents=True, exist_ok=True)
                    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                        zf.extractall(BUILD_DIR)
                        print(f"[CI] Extracted files to {BUILD_DIR}: {zf.namelist()}")
                    dylib_downloaded = True

        if all_done:
            arts = api_get(
                f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts",
                token,
            ).get("artifacts", [])
            for a in arts:
                if a["name"] == "FLM_CustomDSP_Bundle_With_Screenshots":
                    print(f"[CI] Downloading screenshots artifact {a['name']}...")
                    zbytes = download_artifact_zip(a["archive_download_url"], token)
                    with zipfile.ZipFile(io.BytesIO(zbytes)) as zf:
                        zf.extractall(BUILD_DIR)
                        print(f"[CI] Extracted screenshot bundle: {zf.namelist()}")
            break

        time.sleep(5)

    compile_log = BUILD_DIR / "compile.log"
    if compile_log.exists():
        print("\n=== compile.log ===")
        lines = compile_log.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-35:]:
            print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
