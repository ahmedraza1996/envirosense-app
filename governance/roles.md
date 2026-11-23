# Roles and accountability (v1, 23 November 2026)

Accountability is stated as responsibility (who answers for it), auditability (what record shows it) and redressability (how it is corrected).

| Role | Person | Responsibility | Record | Redress |
| --- | --- | --- | --- | --- |
| Accountable owner of each release | Principal investigator (Ahmed Raza) | Data handling, models, thresholds, software, documentation, risk register; proposes a release | Decision log; experiment log; app log; git history | Correct or withdraw a release; record in the incident log |
| Independent reviewer and release approver | Supervisor [to be named] | Reviews the research design, evaluation protocol and limits statement; approves a release (new default model, new thresholds, final report) | Approval entry in the decision log | Can refuse or withdraw an approval |
| Analyst (application role) | A signed-in user of a unit | Runs assessments, uploads imagery, proposes an alert for confirmation, marks it as needing information or dismisses it, with a reason | Review history (account, role, unit, time, status, reason); audit log | Can change a decision they made; history is kept |
| Approving officer (application role) | A signed-in user of a unit | Confirms an alert that another person proposed, retracts a confirmed alert with a reason, exports alert lists, deletes uploads in the unit tree; cannot confirm their own proposal | Review history; audit log | Retraction route; history is kept |
| Auditor (application role) | A signed-in user | Reads the audit log, verifies its chain and reads review history; no imagery, alert lists or exports; cannot change anything | Audit log of their reads is not kept | Reports findings to the accountable owner |
| System administrator (application role) | A signed-in user of a unit | Creates and disables users and units in their unit tree, resets passwords, changes the approved model with a reason; no access to imagery or alerts | Audit log; decision log | Another administrator can reverse a change |
| Provider of reference data | xBD authors; OpenStreetMap contributors | Datasets and map data, under their licences | Datasheet; attribution | Report data problems to the source |
| AI coding assistant | Claude (Anthropic), under the investigator's direction | Drafts code, runs experiments and measurements, drafts text | Declared in the proposal (section 14); recorded in the logs | The investigator remains responsible for the content |

Independence note: a single investigator cannot independently review their own work. The supervisor's approval is the independent check; the oversight test uses a small
number of reviewers and the assurance report will state how many.

## Who does what at each stage

| Stage | Does it | Approves or checks it | Cannot |
| --- | --- | --- | --- |
| Training data, training, evaluation | Principal investigator: trains, writes the run record and model card, runs the evaluation | Supervisor: reads the scorecard against the acceptance criteria | The investigator cannot approve their own release |
| Model release | An administrator files the approval request with a reason (and a written exception if the release gate is closed) | A second administrator approves; the supervisor signs off in the decision log | No silent model change; the gate cannot be skipped without a written exception |
| Thresholds | An administrator files the change with a reason | A second administrator approves | Values are never edited, only added as versions |
| Image intake | Analyst: uploads with source, licence and the rights confirmation; checks the alignment | Input checks; the analyst confirms the alignment | Upload without source, licence and confirmation |
| Prediction | The system: abstains when an input check fails or the model is unsure | Analyst reads the flags | The system cannot raise alerts on an abstained image |
| Area alerts | Analyst proposes, asks for information or dismisses (with a reason) | A different approving officer confirms or retracts (with a reason) | Nobody confirms their own proposal (database rule) |
| Export | Approving officer | Every export and report is in the audit log | Analysts and auditors cannot export |
| Monitoring | The system: live precision, drift, abstention, review behaviour; raises incidents | Administrators and auditors read the Monitoring page | |
| Incidents | Anyone reports one | An administrator or officer assesses and closes it with the cause; a serious one goes to the supervisor within 24 hours | Incidents cannot be deleted |
| Risks | An administrator edits the risk register with a reason | The supervisor at the quarterly review | |
| Access | An administrator creates accounts and reviews them every 3 months | Another administrator reviews the reviewer's own account | Administrators see no imagery or alerts; nobody reviews their own account |
| Audit | The auditor reads the audit log and the Compliance page and verifies the chain | Reports findings to the principal investigator | The auditor changes nothing and sees no imagery |
