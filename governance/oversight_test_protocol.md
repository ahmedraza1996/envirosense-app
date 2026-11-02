# Oversight test with seeded errors: protocol (v0.1, 3 November 2026)

Control H3. Question: when the model is wrong, do people catch it, or do they accept what the screen shows? Human oversight is claimed in the intended-use statement;
this test measures it (after Green 2022, who shows that oversight often does not work as assumed).

## Material

- 12 to 20 alerts on benchmark tiles from the hold partition, where xBD labels give the truth for each alert area: an alert is **true** when at least half of the true building
  area inside its outline is major or destroyed in the labels, **false** otherwise. Alerts are taken from the approved model's output, so errors are real model errors, not invented.
- At least 5 false alerts (real false alarms from the model). If the model has too few, add seeded ones: alerts raised on areas whose labels are all undamaged, with the same
  appearance in the interface. Seeded alerts are listed in a private key and flagged `seeded` there only.
- Order is shuffled per reviewer. Reviewers are not told how many are false.

## Reviewers and roles (use the accounts)

- At least 2 analysts (they propose, dismiss or ask for information) and at least 1 approving officer from another account (they confirm or return). Not the investigator.
- Each reviewer sees each alert once, with the normal interface: map, evidence strength ("unsure structures"), flags. One session of about 30 minutes.
- Two conditions for a subset of reviewers: with the model's confidence and evidence strength visible (normal) and without them, to see whether the cue helps.

## Measures

- Catch rate: share of false alerts dismissed or returned (not proposed). Wrongly dismissed: share of true alerts dismissed. Both with 95% Wilson intervals.
- Four-eyes effect: of false alerts that an analyst proposed, how many the officer returned or dismissed.
- Agreement between reviewers (Cohen's kappa on propose or dismiss).
- Time per alert; use of the note field; whether reviewers who saw "weak evidence: check first" caught more.
- Reviewer comments on what was unclear (free text).

## Criterion

AC-5 in `acceptance_criteria.md`: at least 80% of false alerts caught and at most 10% of true alerts wrongly dismissed. The number of reviewers and alerts is reported; with few
reviewers the result is described, not generalised.

## Procedure and records

1. Prepare the alert set and the private key (assessment ids, alert ids, truth, seeded or not); store the key outside the app.
2. Create reviewer accounts (administrator), brief reviewers with the intended-use statement only.
3. Reviewers work in the app; every decision is recorded by account in the review history and audit log.
4. Score from the review store and the key; write `reports/oversight_test.md` with the table, intervals, comments and the limits.
5. Add rows to `incident_log.md` for any seeded alert that was confirmed by an officer (it is a drill of the incident procedure, control I2).

## Limits to state

Small group, one session, benchmark tiles, reviewers who know they are being tested. The test measures what this setup caught, not the rate in real use.
