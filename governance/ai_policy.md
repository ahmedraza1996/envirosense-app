# AI policy for EnviroSense (v1, 23 November 2026)

Control G5. Owner: principal investigator. Approved by: supervisor [pending]. Reviewed every 6 months and after any serious incident.

## 1. What the system is for
EnviroSense helps disaster-management analysts decide **which areas to inspect first** after a disaster, from before and after satellite images.
It drafts area alerts; people confirm, dismiss or retract every one of them. The full statement of use, excluded uses and limits is
`intended_use.md`.

## 2. Rules
1. **People decide.** No alert leaves the system without a named analyst proposing it and a different approving officer confirming it
   (four-eyes, held by the database). Nothing is sent anywhere automatically.
2. **The system says when it does not know.** When an input check fails or most structures are unsure, the system abstains: it shows
   "Not assessed: needs a person" instead of a guess.
3. **Only an approved model runs by default.** A model is approved by two administrators, against acceptance criteria written before its
   results were known. A model that misses a criterion is released only with a written exception, kept in the decision log.
4. **Every value that changes behaviour is versioned.** Thresholds (review confidence, the alert rule, the monitoring floors) change only
   by a two-person approval, as a new version; nothing is edited in place.
5. **Imagery is used only with the right to use it.** Every upload records its source, its licence and who confirmed the right to process
   it; camera and device metadata are removed; uploads are deleted after the retention period.
6. **Everything is on the record.** Every action is in the hash-chained audit log; every result carries its input, model and code hashes.
7. **Problems are incidents.** A retracted alert, a quality floor crossed or a security worry is an incident, assessed and closed with its
   cause. A serious incident reaches the supervisor within 24 hours.
8. **Separation of duties.** Whoever manages accounts or reads the audit log does not handle imagery or alerts.

## 3. Frameworks it is measured against
Pakistan is the legal setting (PECA 2016; the Personal Data Protection Bill, draft; the National AI Policy 2025, status to be confirmed
against the official texts). The EU AI Act (high-risk requirements, Articles 9 to 17, 27, 72, 73), NIST AI RMF 1.0, ISO/IEC 42001 with
23894 and 42005, the OECD AI Principles and DAMA-DMBOK / OCHA data responsibility are used as the yardstick. How each is applied:
`frameworks.json`; the live status: the Compliance page.

## 4. Who is responsible
`roles.md`. The principal investigator owns this policy and every release; the supervisor is the independent reviewer and approver.
