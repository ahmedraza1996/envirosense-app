# Acceptance criteria for a release (v0.1, written 3 November 2026)

Control V1. These criteria are written **before** the runs they judge: the seed repeats (WP-M3), the event-grouped U-Net fold (WP-M4), the alert-threshold
tuning (X10), the oversight test (H3) and the final report. A release is accepted only if every criterion below is met on the evidence named; a criterion
that is missed is reported as missed, not rewritten. A change to this file after 3 November 2026 needs an entry in `decision_log.md` with the reason.

Status: proposed by the principal investigator; supervisor approval pending [supervisor, pending].

Honesty note: E14 and E15 were each trained once and scored on the test and hold partitions before this file was written, so AC-1 and AC-3 were set with those
numbers in view (below them, to leave room for seed variation). They are not blind. The criteria for runs that do not exist yet (AC-2, AC-5) are set without
any result in view.

| ID | Criterion | Evidence | Basis |
| --- | --- | --- | --- |
| AC-1 | The release model, mean over three seeds, scores at least 0.60 on the hold partition (xView2 score), no single seed below 0.58; localisation F1 at least 0.75; destroyed-class F1 at least 0.60; minor-class F1 at least 0.33 | `reports/experiment_log.md` (seed entry), `runs/*/hold_metrics.json` | Single-seed results: E15 0.644 hold, loc 0.776, destroyed 0.64, minor 0.37 on test; E14 0.623 hold |
| AC-2 | On the event-grouped fold (events never seen in training), the score is reported per event; the mean is at least 0.40 and no event named in the release notes scores below 0.30 | event-grouped entry in the experiment log | Not yet measured for the U-Net; set without a result in view |
| AC-3 | With registration on, the score keeps at least 90% of its stored value under an 8 px shift and at least 80% under a 2 degree rotation | robustness table, 156 hold tiles | E15 keeps 96% and 89%; E14 keeps 92% and 79%, so E14 would fail the rotation criterion |
| AC-4 | Expected calibration error of the damage head at most 0.05 on validation pairs; the error rate among pixels kept at the review threshold (0.7) at most 8% | `runs/<run>/calibration.json` | E17: calibrated within 1.5 points; 4 to 6% error among kept pixels at 0.7 |
| AC-5 | In the oversight test with seeded errors, reviewers dismiss or return at least 80% of the planted false alerts and dismiss at most 10% of the true alerts; the interval (95% Wilson) is reported with the numbers, and the number of reviewers and alerts is stated | `reports/oversight_test.md` (to be written, protocol in `oversight_test_protocol.md`) | Not yet run; set without a result in view |
| AC-6 | The audit chain verifies; every action that changes state is in the audit log (test); an exported alert traces to its input hashes and checkpoint hash (test); every control marked in place names evidence that exists (test) | `tests/test_governance.py`, `tests/test_access.py`, `GET /api/audit/verify` | Controls AC1 to AC6, X1, X2 |
| AC-7 | The datasheet and model card are complete: no "[to confirm]" remains in the licence and terms section; the model card states seeds, intervals and the event-grouped result | `datasheet_xbd.md`, `model_card_unet_paired.md` | Controls D3, D4, T2 |
| AC-8 | Every incident (retraction, denied action pattern, failed gate shown to a user) in the test period is in the incident log with a cause and a decision | `governance/incident_log.md` | Procedure in `incident_procedure.md` |

## How a result is judged

1. The run is made once with the settings in the experiment log entry, before the result is read.
2. The numbers are compared with this table by someone other than the person who trained the model where possible (the supervisor reads the table, not the code).
3. If a criterion is missed, the release statement says which one, by how much, and what that means for use. The excluded uses in `intended_use.md` stay in force.
