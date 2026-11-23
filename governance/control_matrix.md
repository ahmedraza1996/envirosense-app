# Control matrix

Generated from `controls.json` by `app/scripts/control_matrix.py`; do not edit by hand. Each control is a check with a rule, an owner and
evidence the application verifies; the live status is on the Compliance page. Framework references are alignment targets, not compliance claims.

## Governance

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| G1 | Intended use, excluded uses and limits | A published statement of what the system is for, what it must not be used for, and its measured limits | Principal investigator | `governance/intended_use.md` (file) | EU Art. 13; NIST GOVERN, MAP; ISO Cl. 4, A.8; OECD 1.1, 1.3; PK National AI Policy 2025 |
| G2 | Risk register kept up to date | Every risk has an owner, controls and a review date; none is past its review date | Principal investigator | `risks_reviewed` (live) | EU Art. 9; NIST MAP, MANAGE; ISO Cl. 6, ISO 23894; OECD 1.4 |
| G3 | Roles and accountability | Who does, approves and checks each stage, and who may not | Principal investigator | `governance/roles.md` (file) | EU Art. 17; NIST GOVERN; ISO Cl. 5, A.3; OECD 1.5; PK National AI Policy 2025 |
| G4 | Decision log | Every change of model, threshold, role or scope is a row with its reason and the people who took it; rows cannot be changed | Principal investigator | `tests/test_governance_modules.py::test_decisions_are_recorded_and_cannot_be_changed` (test) | EU Art. 17; NIST GOVERN; ISO Cl. 7; OECD 1.5 |
| G5 | AI policy | The organisation's rules for building and using AI in this system, and the frameworks it is measured against | Principal investigator | `governance/ai_policy.md` (file) | NIST GOVERN; ISO Cl. 5, A.2; OECD 1.5; PK National AI Policy 2025 |
| G6 | Technical file from the records | The technical documentation is produced from the live records, not written separately | Principal investigator | `tests/test_governance_modules.py::test_technical_file_lists_every_control` (test) | EU Art. 11; ISO Cl. 7; OECD 1.3 |
| G7 | Impact assessment | Who is affected, what can go wrong for them, and what reduces it | Principal investigator | `governance/impact_assessment.md` (file) | EU Art. 27; NIST MAP; ISO Cl. 8, A.5, ISO 42005; OECD 1.1, 1.2 |
| G8 | Internal audit every 3 months | A person not involved in the work checks the controls and records the result | Supervisor | `governance/records/internal_audit_*.md` (record) | NIST GOVERN; ISO Cl. 9; OECD 1.5 |

## Training data

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| D1 | Archives verified by hash | The dataset files match their published hashes before use | Principal investigator | `../configs/xbd_sha1.txt` (file)<br>`../scripts/verify_xbd.sh` (file) | EU Art. 10; NIST MAP; ISO A.7; DATA DAMA quality |
| D2 | Licence and terms recorded | The dataset licence is written in the datasheet, nothing left to confirm | Principal investigator | `licence_recorded` (live) | EU Art. 10; ISO A.7, A.10; DATA DAMA metadata; PK PECA 2016 |
| D3 | Datasheet | Composition, collection, uses and limits of the training data | Principal investigator | `governance/datasheet_xbd.md` (file) | EU Art. 10, Art. 11; NIST MAP; ISO A.7; DATA DAMA metadata |
| D4 | No leakage between splits | No image pair is in more than one of train, test and hold | Principal investigator | `tests/test_governance_modules.py::test_no_pair_is_in_two_splits` (test)<br>`leakage_free` (live) | EU Art. 10; NIST MEASURE; ISO A.7; DATA DAMA quality |

## Training

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| T1 | Complete run record | The approved model's run records its code version, data-split hash, seed and command | Principal investigator | `approved_run_record` (live) | EU Art. 11, Art. 12; NIST MEASURE; ISO A.6; DATA DAMA lineage |
| T2 | Model card from the run | The approved model has a model card written from its own run records | Principal investigator | `approved_model_card` (live) | EU Art. 11; NIST MAP, MEASURE; ISO A.6, A.8; OECD 1.3 |
| T3 | Training cannot exhaust the server | Training stops itself, after saving, when free memory runs low | Principal investigator | `../src/seg_benchmark.py` (file_contains) | EU Art. 15; ISO A.4; OECD 1.4 |
| T4 | Results repeated over three seeds | The approved model's result is repeated with three training runs | Principal investigator | `seeds_measured` (live) | EU Art. 15; NIST MEASURE; ISO A.6; OECD 1.4 |

## Evaluation

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| V1 | Pass marks set before the final runs | Acceptance criteria written down before the results they judge | Supervisor | `governance/acceptance_criteria.json` (file)<br>`governance/acceptance_criteria.md` (file) | EU Art. 15; NIST MEASURE; ISO Cl. 8, A.6 |
| V2 | Approved model meets every pass mark | The approved model passes every acceptance criterion | Supervisor | `approved_model_gate` (live) | EU Art. 15; NIST MEASURE, MANAGE; ISO A.6; OECD 1.4 |
| V3 | Score on disasters never seen in training | The approved model is scored on whole disasters left out of training | Principal investigator | `unseen_measured` (live) | EU Art. 15; NIST MEASURE; ISO A.6; OECD 1.2, 1.4 |
| V4 | Robustness and calibration measured | Misaligned images and confidence are measured for the approved model | Principal investigator | `robustness_measured` (live) | EU Art. 15; NIST MEASURE; ISO A.6; OECD 1.4 |

## Model release

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| R1 | Release gate | A model that misses a pass mark is released only with a written exception the approver sees | Administrators | `tests/test_governance_modules.py::test_release_gate_blocks_a_model_that_misses_criteria_unless_an_exception_is_given` (test) | EU Art. 9, Art. 17; NIST MANAGE; ISO Cl. 8, A.6 |
| R2 | Two people for every sensitive change | The model, a threshold or a role changes only when a second eligible person approves | Administrators | `tests/test_approvals.py::test_with_two_administrators_a_model_change_waits_for_the_other` (test) | EU Art. 17; NIST GOVERN, MANAGE; ISO A.3, A.6; OECD 1.5 |
| R3 | Approved file is the evaluated file | The approved model's checkpoint on disk matches its recorded hash | Administrators | `approved_model_hash` (live) | EU Art. 12, Art. 15; ISO A.6; OECD 1.4 |
| R4 | Rollback ready | The previously approved model is still available to switch back to | Administrators | `previous_model_available` (live) | EU Art. 9; NIST MANAGE; ISO A.6 |

## Image intake

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| I1 | Rights to the imagery | Source, licence and a confirmation of the right to process are required for every upload | Analysts | `tests/test_governance_modules.py::test_upload_needs_source_licence_and_rights` (test)<br>`uploads_have_rights` (live) | EU Art. 10; ISO A.7, A.10; DATA OCHA data responsibility, DAMA metadata; PK PDP Bill (draft) |
| I2 | Input quality and unusual images | Each upload's statistics are compared with the training range; blank, cloudy and unusual images are flagged | Analysts | `tests/test_governance_modules.py::test_unusual_and_blank_images_are_flagged` (test)<br>`reference_stats` (live) | EU Art. 10, Art. 15; NIST MEASURE; ISO A.7; DATA DAMA quality; OECD 1.4 |
| I3 | Camera and device metadata removed | EXIF, XMP, IPTC and text metadata are removed from uploaded files; georeference is kept | Analysts | `tests/test_governance_modules.py::test_metadata_is_stripped_from_jpeg_and_png` (test) | OECD 1.2; DATA OCHA data responsibility; PK PDP Bill (draft) |
| I4 | A person confirms the alignment | The assessment waits until a person has checked that the before and after images line up | Analysts | `tests/test_uploads.py::test_alignment_is_checked_before_the_assessment` (test) | EU Art. 14; NIST MANAGE; ISO A.9 |
| I5 | Retention period | Uploaded imagery is deleted after a set period | Administrators | `retention_set` (live)<br>`tests/test_governance.py::test_retention_rule_deletes_only_expired_uploads` (test) | DATA DAMA retention, OCHA data responsibility; PK PDP Bill (draft) |

## Prediction

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| P1 | Abstain instead of guess | When an input check fails or most structures are unsure, no alert is raised and the area is shown as not assessed | Analysts | `tests/test_governance_modules.py::test_assessment_abstains_when_a_check_fails_or_most_structures_are_unsure` (test) | EU Art. 14, Art. 15; NIST MANAGE; ISO A.9; OECD 1.4 |
| P2 | Unsure structures marked for review | Structures below the review confidence are drawn dashed and counted | Analysts | `tests/test_governance.py::test_gates_flag_what_the_analyst_must_know` (test) | EU Art. 13, Art. 14; NIST MANAGE; ISO A.8; OECD 1.3 |
| P3 | Provenance on every result | Input, model and code hashes and the thresholds used are stored with each result | Analysts | `tests/test_governance.py::test_provenance_hashes_inputs_and_checkpoint` (test) | EU Art. 12; NIST MEASURE; ISO A.6; DATA DAMA lineage; OECD 1.5 |
| P4 | Only the approved model by default | The default model is the approved one, never the best test score | Administrators | `tests/test_governance.py::test_default_model_is_the_approved_one` (test) | EU Art. 17; NIST MANAGE; ISO A.6 |

## Area alerts

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| A1 | Drafts only | Every alert starts as a draft; nothing is sent anywhere automatically | Officers | `tests/test_features.py::test_review_lifecycle_and_export` (test) | EU Art. 14; NIST MANAGE; ISO A.9; OECD 1.5 |
| A2 | Versioned alert rule | The alert rule's values are thresholds: changed only by two people, never edited, each version kept | Administrators | `tests/test_governance_modules.py::test_alert_rule_comes_from_versioned_thresholds` (test)<br>`tests/test_governance_modules.py::test_thresholds_cannot_be_edited_only_added` (test)<br>`thresholds_versioned` (live) | EU Art. 12, Art. 17; NIST MANAGE; ISO A.6 |
| A3 | Alerts trace to their inputs | Each exported alert carries its rule version, input and model hashes | Officers | `tests/test_governance.py::test_exported_alert_traces_to_its_inputs_and_checkpoint` (test) | EU Art. 12, Art. 13; ISO A.8; DATA DAMA lineage; OECD 1.3 |

## Human review

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| H1 | Four-eyes confirmation | The person who confirms an alert is not the person who proposed it (held by the database) | Officers | `tests/test_database.py::test_the_database_refuses_a_confirmation_by_the_person_who_proposed` (test) | EU Art. 14; NIST MANAGE; ISO A.9; OECD 1.5 |
| H2 | Reasons and history | A reason is required to dismiss or retract; the review history cannot be edited | Officers | `tests/test_governance.py::test_review_needs_name_and_reason_and_keeps_history` (test) | EU Art. 12, Art. 14; ISO A.9; OECD 1.5 |
| H3 | Rubber-stamp measure | Confirmations made in under 5 seconds or without opening the evidence are counted | Officers | `tests/test_governance_modules.py::test_review_behaviour_counts_quick_confirmations` (test) | EU Art. 14; NIST MEASURE; ISO A.9 |
| H4 | Oversight test every 3 months | Reviewers are tested with planted false alerts; they must catch at least 80% | Supervisor | `governance/records/oversight_test_*.md` (record) | EU Art. 14; NIST MEASURE; ISO Cl. 9, A.9 |

## Export

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| E1 | Export right, every export logged | Alert files and reports need the export right; each download is an audit row | Officers | `tests/test_governance_modules.py::test_reports_need_export_and_are_logged` (test) | EU Art. 12; ISO A.8; DATA OCHA data responsibility; PK PECA 2016 |
| E2 | Labelled exports | Draft marker, model version and limits on every export and report | Officers | `tests/test_features.py::test_report_follows_the_review` (test) | EU Art. 13; ISO A.8; OECD 1.3 |
| E3 | Own unit only | People see and export only their own unit's work and the units below it | Administrators | `tests/test_access.py::test_uploads_are_visible_only_inside_the_owner_unit_tree` (test) | DATA OCHA data responsibility, DAMA security; PK PECA 2016 |

## Monitoring

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| M1 | Live accuracy above the floor | The share of recent reviewed alerts people confirmed stays above the floor | Administrators | `live_precision_ok` (live)<br>`tests/test_governance_modules.py::test_live_precision_below_floor_raises_one_incident` (test) | EU Art. 72; NIST MEASURE, MANAGE; ISO Cl. 9; OECD 1.4 |
| M2 | Drift in the uploads | The share of unusual uploads is watched month by month | Administrators | `drift_ok` (live)<br>`tests/test_governance_modules.py::test_drift_raises_an_incident` (test) | EU Art. 72; NIST MEASURE; ISO Cl. 9; DATA DAMA quality |

## Incidents

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| N1 | Incident register | Incidents are opened, assessed and closed with a cause; nothing is deleted | Administrators | `tests/test_governance_modules.py::test_incidents_open_assess_close_and_cannot_be_deleted` (test) | EU Art. 73; NIST MANAGE; ISO Cl. 10; OECD 1.5 |
| N2 | A retraction opens an incident | Retracting a confirmed alert opens an incident automatically | Officers | `tests/test_governance_modules.py::test_retraction_raises_an_incident` (test) | EU Art. 73; NIST MANAGE; ISO Cl. 10 |
| N3 | Urgent incidents handled within 7 days | No high or serious incident stays open more than 7 days | Administrators | `incidents_handled` (live) | EU Art. 73; NIST MANAGE; ISO Cl. 10 |
| N4 | Incident drill every 6 months | A rehearsed wrong-alert incident, from retraction to closure, with its time recorded | Supervisor | `governance/records/incident_drill_*.md` (record) | EU Art. 73; NIST MANAGE; ISO Cl. 10 |

## Every stage

| # | Control | Rule | Owner | Evidence | Frameworks |
| --- | --- | --- | --- | --- | --- |
| F1 | Individual accounts | Personal accounts, hashed passwords, lock-out after failed attempts | Administrators | `tests/test_access.py::test_login_logout_lockout_and_password_rules` (test) | EU Art. 15; NIST GOVERN; ISO A.4; DATA DAMA security; PK PECA 2016 |
| F2 | Separation of duties | No role combines account management or audit with handling imagery or alerts (held by the database) | Administrators | `tests/test_database.py::test_a_role_cannot_combine_permissions_that_must_stay_apart` (test) | NIST GOVERN; ISO A.3; OECD 1.5 |
| F3 | Tamper-evident audit log | Every action is a chained, append-only row; the chain verifies | Administrators | `tests/test_governance.py::test_the_database_itself_refuses_to_change_or_break_the_audit_chain` (test)<br>`audit_chain` (live) | EU Art. 12; NIST GOVERN; ISO Cl. 7; OECD 1.5; PK PECA 2016 |
| F4 | Deny by default | Every route has an access rule; anything without one is refused | Administrators | `tests/test_access.py::test_sign_in_is_required_and_every_route_has_a_rule` (test) | EU Art. 15; ISO A.4; DATA DAMA security; PK PECA 2016 |
| F5 | Access reviewed every 3 months | An administrator confirms that each active account is still needed | Administrators | `access_review_current` (live)<br>`tests/test_governance_modules.py::test_access_review_cannot_review_yourself_and_disable_ends_access` (test) | NIST GOVERN; ISO A.3; DATA DAMA security; PK PECA 2016 |
| F6 | Two-step sign-in | Administrators and approving officers sign in with a password and a code from an authenticator app | Administrators | `two_step_coverage` (live)<br>`tests/test_governance_modules.py::test_two_step_sign_in` (test) | EU Art. 15; ISO A.4; DATA DAMA security; PK PECA 2016 |
| F7 | No shared demo accounts in real use | The demo accounts with the published password are switched off | Administrators | `demo_accounts_off` (live) | EU Art. 15; NIST GOVERN; OECD 1.5; PK PECA 2016 |

## How each framework is applied

### EU AI Act (benchmark)

Legal checklist for high-risk AI systems, used as a yardstick: the system is operated in Pakistan, so the Act does not apply by law. Each article is the acceptance condition of the controls tagged with it. The technical file is produced from the same records (Annex IV style). Status is met when every tagged control is met.

| Requirement | Controls |
| --- | --- |
| Art. 9 Risk management system | G2, R1, R4 |
| Art. 10 Data and data governance | D1, D2, D3, D4, I1, I2 |
| Art. 11 Technical documentation | G6, D3, T1, T2 |
| Art. 12 Record-keeping (automatic logs) | T1, R3, P3, A2, A3, H2, E1, F3 |
| Art. 13 Transparency and information to deployers | G1, P2, A3, E2 |
| Art. 14 Human oversight | I4, P1, P2, A1, H1, H2, H3, H4 |
| Art. 15 Accuracy, robustness and cybersecurity | T3, T4, V1, V2, V3, V4, R3, I2, P1, F1, F4, F6, F7 |
| Art. 17 Quality management system | G3, G4, R1, R2, P4, A2 |
| Art. 27 Fundamental-rights impact assessment (public bodies deploying) | G7 |
| Art. 72 Post-market monitoring | M1, M2 |
| Art. 73 Reporting of serious incidents | N1, N2, N3, N4 |

### NIST AI RMF 1.0

Voluntary framework; the working loop of the management system. Read the control register by function. The status per function is the current profile; the target profile is every function met. No certificate exists.

| Requirement | Controls |
| --- | --- |
| GOVERN Policies, roles, accountability and culture | G1, G3, G4, G5, G8, R2, F1, F2, F3, F5, F7 |
| MAP Context, intended use, risks and impacts | G1, G2, G7, D1, D3, T2 |
| MEASURE Metrics, testing and evaluation | D4, T1, T2, T4, V1, V2, V3, V4, I2, P3, H3, H4, M1, M2 |
| MANAGE Treat risks, respond to incidents, monitor and improve | G2, V2, R1, R2, R4, I4, P1, P2, P4, A1, A2, H1, M1, N1, N2, N3, N4 |

### ISO/IEC 42001 (with 23894 and 42005)

Certifiable AI management system; here an internal audit against it, no certification sought. Clauses 4 to 10 are the governance layer; the Annex A areas are carried by the controls tagged with them. This register is the statement of applicability.

| Requirement | Controls |
| --- | --- |
| Cl. 4 Context of the organisation | G1 |
| Cl. 5 Leadership: policy and roles | G3, G5 |
| Cl. 6 Planning: risk assessment and objectives | G2 |
| Cl. 7 Support: resources and documented information | G4, G6, F3 |
| Cl. 8 Operation: impact assessment and life cycle | G7, V1, R1 |
| Cl. 9 Performance evaluation: monitoring, internal audit | G8, H4, M1, M2 |
| Cl. 10 Improvement: nonconformity and corrective action | N1, N2, N3, N4 |
| A.2 Policies related to AI | G5 |
| A.3 Internal organisation | G3, R2, F2, F5 |
| A.4 Resources for AI systems | T3, F1, F4, F6 |
| A.5 Assessing impacts of AI systems | G7 |
| A.6 AI system life cycle | T1, T2, T4, V1, V2, V3, V4, R1, R2, R3, R4, P3, P4, A2 |
| A.7 Data for AI systems | D1, D2, D3, D4, I1, I2 |
| A.8 Information for interested parties | G1, T2, P2, A3, E1, E2 |
| A.9 Use of AI systems | I4, P1, A1, H1, H2, H3, H4 |
| A.10 Third-party relationships | D2, I1 |
| ISO 23894 Risk management method | G2 |
| ISO 42005 Impact assessment method | G7 |

### OECD AI Principles

Values the system is checked against; the OECD classification framework profiles the system once (governance/impact_assessment.md). Each principle points at the controls that put it into practice.

| Requirement | Controls |
| --- | --- |
| 1.1 Inclusive growth, sustainable development and well-being | G1, G7 |
| 1.2 Human rights and democratic values, fairness and privacy | G7, V3, I3 |
| 1.3 Transparency and explainability | G1, G6, T2, P2, A3, E2 |
| 1.4 Robustness, security and safety | G2, T3, T4, V2, V3, V4, R3, I2, P1, M1 |
| 1.5 Accountability | G3, G4, G5, G8, R2, P3, A1, H1, H2, N1, F2, F3, F7 |

### Data governance (DAMA-DMBOK, OCHA Data Responsibility)

Practice for the training data and the uploaded imagery. DAMA knowledge areas and the OCHA data-responsibility guidance as a checklist for the data controls.

| Requirement | Controls |
| --- | --- |
| DAMA quality Data quality | D1, D4, I2, M2 |
| DAMA metadata Metadata and documentation | D2, D3, I1 |
| DAMA lineage Lineage: from input to result | T1, P3, A3 |
| DAMA security Data security and access | E3, F1, F4, F5, F6 |
| DAMA retention Retention and deletion | I5 |
| OCHA data responsibility Humanitarian data responsibility: minimum data, known recipients | I1, I3, I5, E1, E3 |

### Pakistan (legal setting)

The laws and policy where the system is used. Status of the data protection bill to be checked against the official text before citing. Applies to image intake (rights, privacy), access and security, and the responsible-AI commitments of the national policy.

| Requirement | Controls |
| --- | --- |
| PECA 2016 Prevention of Electronic Crimes Act 2016 (unauthorised access, data security) | D2, E1, E3, F1, F3, F4, F5, F6, F7 |
| PDP Bill (draft) Personal Data Protection Bill (draft) | I1, I3, I5 |
| National AI Policy 2025 National AI Policy 2025: responsible, human-overseen AI | G1, G3, G5 |
