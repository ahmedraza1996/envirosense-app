"""Semantic layer: damage classes, metric definitions, glossary and the review threshold

Revision ID: 0002
Revises: 0001
"""
import json

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

XBD = "xBD joint damage scale (Gupta et al., 2019)"
CLASSES = [
    (0, "no-damage", "No damage", "#3F8F5F", False, "Undisturbed building: no sign of water, structural or shingle damage, or burn marks."),
    (1, "minor-damage", "Minor damage", "#D9A520", False, "Building partially burnt, surrounded by water, roof elements missing, or visible cracks."),
    (2, "major-damage", "Major damage", "#D9622B", True, "Partial wall or roof collapse, or surrounded by water or mud."),
    (3, "destroyed", "Destroyed", "#B3261E", True, "Scorched, completely collapsed, covered by water or mud, or no longer present."),
]
METRICS = [
    ("xview2_score", "xView2 score",
     "The competition score for building damage assessment: how well buildings are located and how well their damage class is graded.",
     "0.3 * localisation_f1 + 0.7 * damage_f1", "score 0-1", "src/metrics.py; xView2 challenge rules"),
    ("localisation_f1", "Localisation F1", "F1 of building pixels (building or not) against the labelled outlines.", "2TP / (2TP + FP + FN) over building pixels", "F1", "src/metrics.py"),
    ("damage_f1", "Damage F1", "Harmonic mean of the F1 scores of the four damage classes, so a class that is never found pulls the score down.",
     "n / sum(1 / F1_class) over the four classes", "F1", "src/metrics.py"),
    ("severe_share", "Severe share", "Share of the building roof area inside an alert area that is classed major damage or destroyed.",
     "severe_roof_m2 / building_area_m2", "share 0-1", "app/api/alerts.py"),
    ("priority_score", "Priority", "Rank value of an alert area: how many severely damaged 100 m2 roofs it holds.", "severe_roof_m2 / 100", "roofs", "app/api/alerts.py"),
    ("expected_calibration_error", "Expected calibration error", "Average gap between the model's confidence and how often it is right, over 15 confidence bins.",
     "sum_b (n_b / n) * |accuracy_b - confidence_b|", "share 0-1", "src/calibrate.py (E17)"),
]
GLOSSARY = [
    ("assessment", "entity", "The model's result for one scene, upload or area: structures, area alerts and the provenance (input hashes, checkpoint hash, thresholds) needed to reproduce it.", ["alert", "provenance"], "app/api/service.py"),
    ("structure", "entity", "A group of connected building pixels found by the model. It is derived on every run and is not a building inventory.", ["assessment"], "app/api/alerts.py"),
    ("alert", "entity", "An area where severely damaged roof is concentrated. It is a draft until an analyst proposes it and a different approving officer confirms it.", ["alert rule", "four-eyes rule"], "app/api/alerts.py"),
    ("alert rule", "rule", "An area is raised when it holds at least 250 m2 of severely damaged roof, with damage within 30 m of each other. Severity is high when at least half of the building area is severely damaged, otherwise medium.", ["alert", "severe share"], "app/api/alerts.py"),
    ("severe damage", "term", "Major damage or destroyed.", ["severe share"], XBD),
    ("severe share", "measure", "Share of building roof area inside an alert that is severely damaged.", ["severe damage"], "app/api/alerts.py"),
    ("review confidence", "rule", "A structure whose highest class probability is below this threshold is marked for review. The current value is in the thresholds table.", ["unsure structure"], "app/api/engines.py"),
    ("unsure structure", "term", "A structure below the review confidence threshold, or one the model did not detect on the after image.", ["review confidence"], "app/api/service.py"),
    ("four-eyes rule", "rule", "An analyst proposes an alert; a different approving officer confirms it. Only an officer retracts or exports. The database refuses a confirmation by the person who proposed it.", ["alert"], "app/api/reviews.py"),
    ("retraction", "rule", "A confirmed alert later found wrong is retracted with a reason, never deleted; its history stays.", ["four-eyes rule"], "app/governance/incident_procedure.md"),
    ("position offset", "term", "The shift between the imagery and a street map, measured in metres, applied to results on the map without changing the stored outlines.", [], "app/api/geocal.py"),
    ("approved model", "rule", "The one model version approved as the default for new assessments. Changing it needs an entry in the decision log and is recorded in the audit log.", ["model version"], "app/governance/decision_log.md"),
    ("model version", "entity", "A trained network identified by its run and the SHA-256 of its checkpoint file, with its test and hold scores.", ["approved model"], "src/seg_benchmark.py"),
    ("unit", "entity", "A node of the organisation tree (authority, department, team). Users see and act on the data of their own unit and the units below it.", ["role"], "app/api/auth.py"),
    ("role", "entity", "What a user may do: administrator, analyst, approving officer or auditor.", ["unit"], "app/api/auth.py"),
    ("ingestion job", "entity", "One run of the upload pipeline: read image, find the before image, check alignment, model, alerts. It has steps, a heartbeat and is retried if its worker dies.", ["assessment"], "app/api/uploads.py"),
    ("provenance", "term", "The recorded inputs of a result: SHA-256 of each input image, the checkpoint hash, the thresholds and the quality flags.", ["assessment"], "app/api/service.py"),
]


def upgrade():
    c = op.get_bind()
    for code, key, label, colour, severe, d in CLASSES:
        c.execute(sa.text("INSERT INTO sem.damage_classes VALUES (:a,:b,:c,:d,:e,:f)"), dict(a=code, b=key, c=label, d=colour, e=severe, f=d))
    for key, name, desc, formula, unit, src in METRICS:
        c.execute(sa.text("INSERT INTO sem.metrics (key, version, name, description, formula, unit, status, owner, effective_from, source_ref) "
                          "VALUES (:k, 1, :n, :d, :f, :u, 'active', 'principal investigator', DATE '2026-11-03', :s)"),
                  dict(k=key, n=name, d=desc, f=formula, u=unit, s=src))
    for term, kind, d, see, src in GLOSSARY:
        c.execute(sa.text("INSERT INTO sem.glossary VALUES (:t, :k, :d, :s, :r)"), dict(t=term, k=kind, d=d, s=see, r=src))
    c.execute(sa.text("INSERT INTO sem.thresholds (key, value, set_by, decision_ref, note) VALUES "
                      "('review_confidence', 0.7, 'migration', 'governance/decision_log.md (review threshold 0.7)', "
                      "'E17: 0.7 keeps about 59% of building pixels at 4 to 6% error')"))


def downgrade():
    op.get_bind().exec_driver_sql("DELETE FROM sem.thresholds; DELETE FROM sem.glossary; DELETE FROM sem.metrics; DELETE FROM sem.damage_classes")
