# Governance control matrix (v0.1, 2 November 2026)

Each control is a document or something in the software that a test can check. Status: **in place** (exists and is evidenced), **partial**, **planned** (with work package).
References are alignment targets, not compliance claims: NIST AI RMF 1.0 functions (GOVERN, MAP, MEASURE, MANAGE); ISO/IEC 42001 and 23894; EU AI Act Articles 9 to 15 (Art.);
OECD AI Principles; OCHA Data Responsibility Guidelines. Work packages (WP) are those of `output/EnviroSense_Gap_Analysis_and_Completion_Plan.md`.

| # | Stage | Control | Status | Evidence (file or test) | Alignment |
| --- | --- | --- | --- | --- | --- |
| G1 | Set-up | Intended-use, excluded-use and limits statement | in place (draft) | `governance/intended_use.md` | GOVERN, MAP; Art. 9, 13; OECD transparency |
| G2 | Set-up | Risk register with owner, controls and residual risk | in place (v0.1, 15 risks) | `governance/risk_register.csv` | MAP; ISO 23894; Art. 9 |
| G3 | Set-up | Roles, accountability and independent approval | in place (draft) | `governance/roles.md` | GOVERN; ISO 42001 roles; OECD accountability |
| G4 | Set-up | Decision log for every default, threshold, scope and release decision | in place | `governance/decision_log.md` | GOVERN; ISO 42001 documented information |
| D1 | Data | Archives verified by hash before use | in place | `scripts/verify_xbd.sh`, `configs/xbd_sha1.txt` | MAP; Art. 10 |
| D2 | Data | Data audit: counts, classes, events, geometry, georeference conflict | in place | `reports/audit_xbd.md` | MEASURE; Art. 10 |
| D3 | Data | Datasheet (composition, collection, use, limits) | draft | `governance/datasheet_xbd.md` | MAP; Art. 10, 11 |
| D4 | Data | Licence and terms of use recorded | planned (WP-G1) | datasheet section 6 | Art. 10; OCHA |
| D5 | Data | Uploads: deletion on request removes images, results and reviews; retention setting and notice | partial (deletion exists) | `api/uploads.py` delete; test in `tests/test_features.py` | OCHA data responsibility; OECD |
| T1 | Training | Frozen splits; run folder with configuration, log, checkpoint, results | in place | `configs/pair_splits.csv`, `runs/*`, `reports/experiments_table.md` | MEASURE, MANAGE; Art. 11, 12 |
| T2 | Training | Model cards | draft (E14, E15) | `governance/model_card_*.md` | MAP, MEASURE; Art. 11 |
| T3 | Training | Seeds and intervals for headline results | planned (WP-M3) | experiment log | MEASURE; Art. 15 |
| V1 | Validation | Acceptance criteria written before the final test run | planned | `governance/acceptance_criteria.md` (to be written, dated) | MEASURE; Art. 15 |
| V2 | Validation | Event-grouped evaluation, per-event reporting | partial (crop classifiers only) | E05; WP-M4 | MEASURE; Art. 15 |
| V3 | Validation | Robustness tests (shift, rotation, zoom) | in place | E14b, E15 robustness, E15c | MEASURE; Art. 15 |
| V4 | Validation | Calibration, ECE, coverage-risk curve | planned (WP-M5) | `src/metrics.py` has `ece` | MEASURE; Art. 15 |
| P1 | Prediction | Provenance record per assessment (model, checkpoint, code version, registration, thresholds) | partial (model, checkpoint, commit, registration QA stored) | assessment JSON | MANAGE; Art. 12 |
| P2 | Prediction | Provenance adds image and checkpoint hashes, offset and thresholds | planned (WP-G2) | `api/provenance.py` (to build) | Art. 12 |
| P3 | Prediction | Input gates (failed registration, low coverage, unmeasured offset, low confidence) with visible flags | planned (WP-G2) | `api/gates.py` (to build); tests | MEASURE, MANAGE; Art. 15 |
| P4 | Prediction | Approved default model; no silent model change | in place | `governance/approved_model.json`; `tests/test_governance.py` | MANAGE; ISO 42001 change control |
| A1 | Alerts | Documented alert rule stored with each assessment; alerts start as drafts; no outside notification | in place | assessment JSON (`alert_rule`); status text | MANAGE; Art. 13 |
| A2 | Alerts | Thresholds tuned on validation and versioned | planned (WP-A) | config file; X10 | MEASURE |
| A3 | Alerts | Alert carries its provenance and gate flags | planned (WP-G2) | alert schema | Art. 12, 13 |
| H1 | Review | Confirm, needs information, dismiss with note; time stamp | in place | `api/reviews.py` | GOVERN, MANAGE; Art. 14 |
| H2 | Review | Named reviewer; append-only history; reason required on dismiss | planned (WP-G2) | `api/reviews.py` (to extend); tests | Art. 14; accountability |
| H3 | Review | Oversight tested with seeded errors | planned (WP-G3) | assurance report | Art. 14; Green 2022 |
| E1 | Export | Report with "Method and limits" | partial | `api/report.py` | Art. 13 |
| E2 | Export | Draft marker, intended use, versions and offset in every export and the report footer | planned (WP-A) | export tests | Art. 13 |
| M1 | Monitoring | Re-evaluation on every new event or retrained model; change log | partial (experiment log, app log) | logs | MANAGE; ISO 42001 continual improvement; Art. 9 |
| M2 | Monitoring | Input-quality summary per upload | planned | upload QA | MEASURE |
| I1 | Incidents | Retraction of an alert; incident log; report revision | planned (WP-G2) | route, log, test | MANAGE; redressability |
| I2 | Incidents | Incident drill | planned (WP-G3) | drill record | MANAGE |
| X1 | Audit | Append-only audit log with hash chain | planned (WP-G2) | `api/audit.py`; test | Art. 12; auditability |
| X2 | Assurance | Traceability test, documentation completeness, gate tests, accountability metrics | planned (WP-G3) | `tests/test_governance.py`; assurance report | SMACTR testing; MEASURE |

Count (2 Nov 2026): 34 controls; in place 11 (G1 to G3 are drafts awaiting supervisor review), draft 2, partial 5, planned 16.
