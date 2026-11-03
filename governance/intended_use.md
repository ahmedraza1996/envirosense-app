# Intended use, excluded uses and limits (v0.1, 2 November 2026)

Status: draft for supervisor review. Owner: principal investigator (Ahmed Raza). Reviewer: supervisor [to be named].
Frameworks used for alignment, not certification: NIST AI RMF 1.0 (Govern, Map), ISO/IEC 23894 (risk method), ISO/IEC 42001 (roles, documented information), EU AI Act Articles 9 to 15 (evidence reference), OECD AI Principles.

## 1. Purpose

EnviroSense is a research prototype that helps an analyst decide **which areas to inspect first** after a disaster. It takes a before and an after
satellite image of an area, finds structures, grades visible damage in four levels (no damage, minor, major, destroyed), groups severe damage into ranked
area alerts and shows each alert with its evidence. The analyst confirms, dismisses or annotates every alert.

## 2. Intended users and setting

- Analysts and students working with optical satellite imagery of 0.3 to 1 m ground resolution, offline or with delayed internet.
- Used on a project server through a local tunnel. Not a public service.

## 3. What the outputs mean

- A damage class describes what is **visible from above** in the images supplied, as judged by a model trained on the xBD dataset.
- An alert says "this area has a lot of severely damaged roof, in the model's judgement". It is a prompt to look, not a finding.
- Every alert starts as a **draft**. Nothing is published, sent or dispatched by the system.

## 4. Excluded uses (the system must not be used for)

1. Dispatching or prioritising the dispatch of emergency services, or any decision about people's safety, without a trained analyst and field verification.
2. Structural-safety or habitability determinations, insurance or legal decisions.
3. Road access, routing or blockage statements.
4. Estimates of residents, casualties or population affected.
5. Imagery of people or conflict settings; use on images the user has no right to process.
6. Any claim of operational or certified performance.

## 5. Known limits (from the project's own measurements)

| Limit | Evidence |
| --- | --- |
| Quality drops on disasters not seen in training | Crop classifiers lost about 0.2 macro-F1 on unseen events (E05); the same test for the full-image models is still to be done |
| Minor damage is the weakest class | F1 0.37 on test for the best model (E15) |
| Flooding under intact roofs is not visible from above | Hurricane Harvey scenario; documented failure |
| Burnt or flooded areas leave nothing to register | Registration declines; shift-only fallback |
| Sensitive to misaligned before/after images | A 2 degree rotation or a 4 m shift costs the previous best model 0.05 to 0.13 of its score; the current model costs less but not nothing (E14b, E15) |
| Position on a street map can be off by tens of metres | About 20 m measured on one xBD tile; spread not yet known (X8) |
| Counts are structures, not buildings | Touching buildings merge |
| xBD covers 19 events and mostly optical, mostly nadir images | Dataset audit |

## 6. Human oversight

The analyst sees the evidence (images, counts, confidence, registration and position status) and can confirm, mark as needing information or dismiss with a
reason. The analyst's decision always overrides the model. Oversight is tested, not assumed (see the oversight test in the assurance plan).

## 7. Data

Training and evaluation use xBD under its terms of use [to confirm]. Uploaded images stay on the project server, are used only for the requested assessment and can be
deleted by the user at any time. No personal data are collected beyond a reviewer name in the review log.

## 8. Change control

A new default model, a new alert threshold or a new data source needs an entry in `decision_log.md` and, for models, an approval by an administrator (`PUT /api/admin/approved-model`, stored in `sem.model_versions` and the audit log).
