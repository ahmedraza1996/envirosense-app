# Decision log

Every change of default model, threshold, data source or scope, and every release approval, is recorded here (date, decision, reason, who decided, approver).
Entries are appended, never edited.

| Date | Decision | Reason | Decided by | Approved by |
| --- | --- | --- | --- | --- |
| 2026-11-02 | AI governance is a main objective of the project, fitted to every pipeline stage; frameworks are used for alignment, not certification | Proposal objective 2 and research question 6 | Principal investigator | [supervisor, pending] |
| 2026-11-02 | The application default model is the one in `approved_model.json`, not the best test score. Pinned to E14 (`unet_paired_ext`) | E15 finished with a better test score (0.625 against 0.591) but the demo set and README numbers were produced with E14, and E15 trades slightly lower destroyed-class F1 and localisation for robustness | Principal investigator | [supervisor, pending] |
| 2026-11-02 | E15 (`unet_paired_mis`) is the candidate default | Test 0.625, hold 0.644, flatter robustness (E15 log entry); switch after the ablation runs and demo-set re-run | Principal investigator | [pending] |
| 2026-11-02 | Out of scope: routing, LLM-written reports, drone data, Docker deployment, certification | Proposal section 5 and gap analysis section 8 | Principal investigator | [supervisor, pending] |
