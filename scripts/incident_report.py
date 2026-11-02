"""Print incident candidates (retractions, denied actions, failed sign-ins) from the audit log and review store.

  uv run --no-sync python app/scripts/incident_report.py [--out reports/incident_candidates.md]
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from app.api import incidents  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out")
    a = p.parse_args()
    text = incidents.markdown(incidents.collect())
    if a.out:
        Path(a.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
