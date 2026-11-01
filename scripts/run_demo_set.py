"""Push every scenario of the demo set through the running app's upload API and print what came back.
Same thing a person does in the upload dialog, so it doubles as an end-to-end check.

  python3 app/scripts/run_demo_set.py [--route tif|jpg] [--only 03] [--url http://127.0.0.1:8765] [--model unet_paired_ext]
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def post(url, name, meta, route, folder, model):
    ext = "tif" if route == "tif" else "jpg"
    cmd = ["curl", "-s", "-m", "120", "-F", f"after=@{folder}/post.{ext}", "-F", f"before=@{folder}/pre.{ext}",
           "-F", f"name={name}", "-F", f"disaster_type={meta['disaster_type']}", "-F", f"event_date={meta['event_date']}",
           "-F", f"model_id={model}"]
    if route == "jpg":
        for k, v in meta["after_corners"].items():
            cmd += ["-F", f"{k}={v}"]
        for k, v in meta["before_corners"].items():
            cmd += ["-F", f"before_{k}={v}"]
    out = subprocess.run(cmd + [f"{url}/api/uploads"], capture_output=True, text=True).stdout
    return json.loads(out)


def get(url):
    return json.loads(urllib.request.urlopen(url, timeout=30).read())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--route", choices=["tif", "jpg"], default="tif")
    p.add_argument("--only", default="")
    p.add_argument("--url", default="http://127.0.0.1:8765")
    p.add_argument("--model", default="unet_paired_ext")
    a = p.parse_args()
    for d in sorted((ROOT / "demo_set").glob("[0-9][0-9]_*")):
        if a.only and not d.name.startswith(a.only):
            continue
        meta = json.loads((d / "metadata.json").read_text())
        r = post(a.url, f"{meta['name']} [{a.route}]", meta, a.route, d, a.model)
        if "id" not in r:
            print(d.name, "REJECTED", r)
            continue
        while True:
            u = get(f"{a.url}/api/uploads/{r['id']}")
            if u["status"]["state"] in ("done", "failed"):
                break
            time.sleep(2)
        if u["status"]["state"] == "failed":
            print(d.name, "FAILED", u["status"].get("error"))
            continue
        rec = get(f"{a.url}/api/assessments/{u['status']['assessment_id']}")
        b, s = rec["scene"]["before"], rec["summary"]["predicted"]
        print(f"{d.name:26s} alerts {len(rec['alerts']):2d} | structures D{s['destroyed']} M{s['major-damage']} m{s['minor-damage']} N{s['no-damage']}"
              f" | before {b['kind']} cover {b['coverage']:.0%} shift {b['shift_m']} m corrected {b['corrected']}")


if __name__ == "__main__":
    sys.exit(main())
