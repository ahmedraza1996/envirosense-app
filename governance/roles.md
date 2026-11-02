# Roles and accountability (v0.1, 2 November 2026)

Accountability is stated as responsibility (who answers for it), auditability (what record shows it) and redressability (how it is corrected).

| Role | Person | Responsibility | Record | Redress |
| --- | --- | --- | --- | --- |
| Accountable owner of each release | Principal investigator (Ahmed Raza) | Data handling, models, thresholds, software, documentation, risk register; proposes a release | Decision log; experiment log; app log; git history | Correct or withdraw a release; record in the incident log |
| Independent reviewer and release approver | Supervisor [to be named] | Reviews the research design, evaluation protocol and limits statement; approves a release (new default model, new thresholds, final report) | Approval entry in the decision log | Can refuse or withdraw an approval |
| Decision-maker for alerts | The analyst using the tool (a named reviewer) | Confirms, marks as needing information or dismisses each alert, with a reason; the decision overrides the model | Review log (name, time, status, reason) | Can change a decision; history is kept; retraction route |
| Provider of reference data | xBD authors; OpenStreetMap contributors | Datasets and map data, under their licences | Datasheet; attribution | Report data problems to the source |
| AI coding assistant | Claude (Anthropic), under the investigator's direction | Drafts code, runs experiments and measurements, drafts text | Declared in the proposal (section 14); recorded in the logs | The investigator remains responsible for the content |

Independence note: a single investigator cannot independently review their own work. The supervisor's approval is the independent check; the oversight test uses a small
number of reviewers and the assurance report will state how many.
