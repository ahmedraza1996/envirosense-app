"""Situation report: numbers must match the stored assessment and add up; every format renders."""
import re

import pytest
from fastapi.testclient import TestClient

from app.api import report, service
from app.api.main import app
from app.api.scenes import catalogue

client = TestClient(app)


@pytest.fixture(scope="module")
def aid():
    df = catalogue()
    pid = df[(df.split == "hold") & (df.buildings.between(20, 60)) & (df.severe_true >= 5)].pair_id.iloc[0]
    return service.assess(pid, "clf_B")["id"]


def test_numbers_match_assessment(aid):
    a = report.load(aid)
    md = report.markdown(aid)
    p, total = a["summary"]["predicted"], a["summary"]["buildings"]
    assert f"| **Total** | **{total}** | 100% |" in md
    for cls, label in [("destroyed", "Destroyed"), ("major-damage", "Major damage"), ("no-damage", "No visible damage")]:
        assert f"| {label} | {p[cls]} |" in md
    assert f"Of {total} buildings" in md
    assert "DRAFT" in md
    assert len(re.findall(r"^\| \d+ \|", md, flags=re.M)) == len(a["zones"])  # one row per priority area


def test_inconsistent_counts_are_refused(aid):
    a = report.load(aid)
    a["summary"]["predicted"]["destroyed"] += 1
    with pytest.raises(report.ReportError):
        report.facts(a)


def test_report_routes(aid):
    r = client.get(f"/api/assessments/{aid}/report.md")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/markdown")
    h = client.get(f"/api/assessments/{aid}/report.html")
    assert h.status_code == 200 and "<h2>Priority areas</h2>" in h.text and "report-map.png" in h.text
    m = client.get(f"/api/assessments/{aid}/report-map.png")
    assert m.status_code == 200 and m.content[:4] == b"\x89PNG"
    assert client.get("/api/assessments/nope__clf_B/report.md").status_code == 404


def test_area_report_lists_every_alert():
    """Footprint-free mode: the report has one row per alert and never mentions xBD outlines as an input."""
    df = catalogue()
    pid = df[(df.split == "hold") & (df.severe_true >= 20)].sort_values("buildings").pair_id.iloc[0]
    rec = service.assess_area(pid, "unet_post")
    md = report.markdown(rec["id"])
    assert "## Area alerts" in md and "No building inventory was used" in md
    assert len(re.findall(r"^\| \d+ \| AL-", md, flags=re.M)) == len(rec["alerts"])
    assert client.get(f"/api/assessments/{rec['id']}/report.html").status_code == 200
    assert client.get(f"/api/assessments/{rec['id']}/report-map.png").status_code == 200
    if rec["features"]:  # a tile can legitimately have no detected structures; the report must still render
        fid = rec["features"][0]["id"]
        assert client.get(f"/api/assessments/{rec['id']}/features/{fid}/crop/post").headers["content-type"] == "image/png"
