"""Writes governance/control_matrix.md from governance/controls.json and governance/frameworks.json (the register is the source; this is its readable copy).
The live status of each control (evidence checked now) is on the Compliance page and in the technical file (GET /api/gov/technical-file.md).

  python app/scripts/control_matrix.py
"""
import json
from pathlib import Path

GOV = Path(__file__).resolve().parents[1] / "governance"


def main():
    c = json.loads((GOV / "controls.json").read_text())
    f = json.loads((GOV / "frameworks.json").read_text())
    ev = lambda e: f"`{e.get('ref') or e.get('check')}` ({e['type']})"
    out = ["# Control matrix", "", "Generated from `controls.json` by `app/scripts/control_matrix.py`; do not edit by hand. Each control is a check with a rule, an owner and",
           "evidence the application verifies; the live status is on the Compliance page. Framework references are alignment targets, not compliance claims.", ""]
    for stage in c["stages"]:
        out += [f"## {stage}", "", "| # | Control | Rule | Owner | Evidence | Frameworks |", "| --- | --- | --- | --- | --- | --- |"]
        for x in (x for x in c["controls"] if x["stage"] == stage):
            fw = "; ".join(f"{k.upper()} {', '.join(v)}" for k, v in x["frameworks"].items())
            out.append(f"| {x['id']} | {x['name']} | {x['rule']} | {x['owner']} | {'<br>'.join(ev(e) for e in x['evidence'])} | {fw} |")
        out.append("")
    out += ["## How each framework is applied", ""]
    for fr in f["frameworks"]:
        out += [f"### {fr['name']}", "", f"{fr['role']} {fr['how']}", "", "| Requirement | Controls |", "| --- | --- |"]
        for r in fr["requirements"]:
            ids = [x["id"] for x in c["controls"] if r["id"] in x["frameworks"].get(fr["key"], [])]
            out.append(f"| {r['id']} {r['title']} | {', '.join(ids)} |")
        out.append("")
    (GOV / "control_matrix.md").write_text("\n".join(out))
    print("wrote", GOV / "control_matrix.md", len(c["controls"]), "controls")


if __name__ == "__main__":
    main()
