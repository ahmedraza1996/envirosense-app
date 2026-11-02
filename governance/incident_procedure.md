# Incident procedure (v0.1, 3 November 2026)

Controls I1 and I2. An incident is anything where the system gave, or could have given, a wrong or unsafe result that reached a user, or where access control or the record was
bypassed. The aim is to correct the result, find the cause and change something so it is less likely to happen again. It is not to assign blame.

## What counts as an incident

| Type | Example | How it is noticed |
| --- | --- | --- |
| Wrong alert released | An alert was confirmed and exported, then found to be wrong (no damage, or the wrong place) | An approving officer retracts it, with a reason |
| Missed damage | Field information shows severe damage that no alert covered | Analyst note (needs information, or a new alert note) |
| Misplaced result | Outlines or alerts sit away from the true position on the map | Analyst measures the position offset (Align) or reports it |
| Access problem | A user sees data outside their unit tree; a denied action repeats; repeated failed sign-ins | Audit log (`denied`, `login_failed` entries); `scripts/incident_report.py` |
| Record problem | The audit chain does not verify; an export cannot be traced to its inputs | `GET /api/audit/verify`; traceability test |
| Model change problem | The default model changed without an approval entry | Decision log against the audit log (`model_approval`) |

## Steps

1. **Contain.** An approving officer retracts the alert (reason required). The retraction is in the review history and the audit log. Exports made earlier cannot be recalled;
   the officer tells whoever received them and records who was told.
2. **Record.** Add a row to `incident_log.md`: date, type, what happened, assessment id and alert id, who found it, who was told. Run
   `uv run --no-sync python app/scripts/incident_report.py` to list retractions, denied actions and failed sign-ins from the records, and copy the relevant lines.
3. **Find the cause.** Use the assessment's provenance (input hashes, checkpoint hash, thresholds, flags) to reproduce the result. Classify the cause: model error, input quality,
   registration or position, threshold, reviewer decision, access control, software defect.
4. **Decide the change.** One of: no change (state why), threshold or gate change, model or default change, documentation or training change, software fix with a test. A change of default
   model or threshold goes to the decision log and needs the supervisor's approval.
5. **Close.** Note the change and its evidence in the incident log; revise the risk register entry the incident relates to (`risk_register.csv`) or add one.
6. **Review.** At each release the accountable owner reads the incident log with the supervisor and states how many incidents occurred and what changed.

## Who does what

| Step | Role |
| --- | --- |
| Retract, tell recipients | Approving officer |
| Record, find cause, propose change | Accountable owner (principal investigator) |
| Read the audit log, confirm what happened | Auditor |
| Approve a change of default, threshold or scope | Supervisor |
| Create or disable accounts after an access problem | System administrator |

## Drill (control I2)

Once before the final report, the investigator seeds one incident (a confirmed alert that is wrong), and a different person runs steps 1 to 5 from this document alone. The time taken, the
steps that were unclear and the changes to this procedure are written in the incident log under "drill".
