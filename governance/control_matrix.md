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
| D5 | Data | Uploads: deletion on request removes images, results and reviews; retention setting and notice | in place (deletion, optional retention rule, notice in the upload dialog) | `api/uploads.py` delete; test in `tests/test_features.py` | OCHA data responsibility; OECD |
| T1 | Training | Frozen splits; run folder with configuration, log, checkpoint, results | in place | `configs/pair_splits.csv`, `runs/*`, `reports/experiments_table.md` | MEASURE, MANAGE; Art. 11, 12 |
| T2 | Training | Model cards | draft (E14, E15) | `governance/model_card_*.md` | MAP, MEASURE; Art. 11 |
| T3 | Training | Seeds and intervals for headline results | planned (WP-M3) | experiment log | MEASURE; Art. 15 |
| V1 | Validation | Acceptance criteria written before the final test run | draft (written 3 Nov 2026, supervisor approval pending) | `governance/acceptance_criteria.md` | MEASURE; Art. 15 |
| V2 | Validation | Event-grouped evaluation, per-event reporting | partial (crop classifiers only) | E05; WP-M4 | MEASURE; Art. 15 |
| V3 | Validation | Robustness tests (shift, rotation, zoom) | in place | E14b, E15 robustness, E15c | MEASURE; Art. 15 |
| V4 | Validation | Calibration, ECE, coverage-risk curve | in place (measured for E14 and E15; temperature not applied because the heads are already calibrated) | `src/calibrate.py`, `runs/<run>/calibration.json`, experiment E17 | MEASURE; Art. 15 |
| P1 | Prediction | Provenance record per assessment (model, checkpoint, code version, registration, thresholds) | in place | assessment JSON: `model`, `provenance` | MANAGE; Art. 12 |
| P2 | Prediction | Provenance adds image and checkpoint hashes, offset and thresholds | in place (assessments made from 2 Nov 2026; older records lack hashes) | `api/provenance.py`; `tests/test_governance.py` | Art. 12 |
| P3 | Prediction | Input gates (failed registration, low coverage, unmeasured offset, low confidence) with visible flags | partial (flags shown; abstention planned, WP-M5) | `api/gates.py`; `tests/test_governance.py` | MEASURE, MANAGE; Art. 15 |
| P4 | Prediction | Approved default model; no silent model change | in place | `db/semantic.py` (`sem.model_versions`, one approved row); `tests/test_governance.py`, `tests/test_database.py` | MANAGE; ISO 42001 change control |
| A1 | Alerts | Documented alert rule stored with each assessment; alerts start as drafts; no outside notification | in place | assessment JSON (`alert_rule`); status text | MANAGE; Art. 13 |
| A2 | Alerts | Thresholds tuned on validation and versioned | planned (WP-A) | config file; X10 | MEASURE |
| A3 | Alerts | Alert carries its provenance and gate flags | in place | `api/reviews.py` (properties and CSV columns `after_sha256`, `before_sha256`, `checkpoint_sha256`, flags); `tests/test_governance.py::test_exported_alert_traces_to_its_inputs_and_checkpoint` | Art. 12, 13 |
| H1 | Review | Confirm, needs information, dismiss with note; time stamp | in place | `api/reviews.py` | GOVERN, MANAGE; Art. 14 |
| H2 | Review | Named reviewer; append-only history; reason required on dismiss | in place | `api/reviews.py` (reviewer, history, reason); `tests/test_governance.py` | Art. 14; accountability |
| H3 | Review | Oversight tested with seeded errors | partial (protocol written; test not yet run) | `governance/oversight_test_protocol.md`; assurance report to follow | Art. 14; Green 2022 |
| E1 | Export | Report with "Method and limits" | partial | `api/report.py` | Art. 13 |
| E2 | Export | Draft marker, intended use, versions and offset in every export and the report footer | in place | `api/reviews.py`, `api/report.py`; tests | Art. 13 |
| M1 | Monitoring | Re-evaluation on every new event or retrained model; change log | partial (experiment log, app log) | logs | MANAGE; ISO 42001 continual improvement; Art. 9 |
| M2 | Monitoring | Input-quality summary per upload | planned | upload QA | MEASURE |
| I1 | Incidents | Retraction of an alert; incident log; report revision | in place | `governance/incident_procedure.md`, `governance/incident_log.md`, `api/incidents.py`, `scripts/incident_report.py`; `tests/test_governance.py::test_incident_report_lists_retractions_denied_actions_and_failed_sign_ins` | MANAGE; redressability |
| I2 | Incidents | Incident drill | planned (WP-G3) | drill record | MANAGE |
| AC1 | Access | Sign-in with individual accounts; hashed passwords; lock-out after 5 failed attempts; temporary passwords must be changed | in place | `api/auth.py`, `api/accounts.py`; `tests/test_access.py` | GOVERN; Art. 14; accountability |
| AC2 | Access | Roles (administrator, analyst, approving officer, auditor); deny-by-default permission table, one rule per route | in place | `auth.POLICY`, `authenticate` in `api/main.py`; `test_sign_in_is_required_and_every_route_has_a_rule`, `test_roles_limit_what_each_user_can_do` | GOVERN; Art. 14 |
| AC3 | Access | Organisation tree: users see and act only on their own unit and the units below; siblings are separated | in place | `auth.in_scope`, `visible_units`; `test_uploads_are_visible_only_inside_the_owner_unit_tree`, `test_audit_log_is_scoped_to_the_callers_unit_tree` | GOVERN; OCHA data responsibility |
| AC4 | Oversight | Four-eyes confirmation: an analyst proposes, a different approving officer confirms; only an officer retracts or exports; the database refuses a self-confirmation | in place | `reviews.set_review`; constraint `four_eyes` in `db/migrations/versions/0001_baseline.sql`; `test_review_needs_name_and_reason_and_keeps_history`, `test_the_database_refuses_a_confirmation_by_the_person_who_proposed` | MANAGE; Art. 14 human oversight |
| AC5 | Audit | Every action is recorded against the signed-in account with its unit and role; denied attempts and failed sign-ins are logged | in place | `api/audit.py`, `api/accounts.py`; `test_login_logout_lockout_and_password_rules` | Art. 12; auditability |
| AC6 | Change control | Only an administrator changes the approved model, with a reason; the change is written to the decision log and the audit log | in place | `PUT /api/admin/approved-model`; `test_only_an_administrator_changes_the_approved_model_and_it_is_logged` | GOVERN; ISO 42001 change control |
| X1 | Audit | Append-only audit log with hash chain, enforced by the database (no update, delete or truncate; each row must follow the last) | in place | `api/audit.py`, `GET /api/audit/verify`; `test_audit_chain_detects_tampering`, `test_the_database_itself_refuses_to_change_or_break_the_audit_chain` | Art. 12; auditability |
| X2 | Assurance | Traceability test, documentation completeness, gate tests, accountability metrics | partial (traceability and documentation-completeness tests exist; gate tests exist; accountability metrics and assurance report to follow) | `tests/test_governance.py::test_every_control_in_place_names_evidence_that_exists`, `tests/test_governance.py::test_exported_alert_traces_to_its_inputs_and_checkpoint` | SMACTR testing; MEASURE |

Count (3 Nov 2026): 40 controls; see the Status column. AC1 to AC6 came with the multi-user access system and are not security-tested (no penetration test, no TLS inside the app). V1 and H3 are written but not yet judged or run.
