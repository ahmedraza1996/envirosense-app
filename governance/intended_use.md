# Intended use, excluded uses and limits (v1, 23 November 2026)

Status: for supervisor review. Owner: principal investigator (Ahmed Raza). Reviewer: supervisor [to be named]. Control G1.
Legal setting: Pakistan. Frameworks used as the yardstick, not certification: EU AI Act (high-risk requirements), NIST AI RMF 1.0, ISO/IEC 42001 with 23894
and 42005, OECD AI Principles, DAMA-DMBOK and OCHA data responsibility (`frameworks.json`, live status on the Compliance page).

## 1. Purpose

EnviroSense is a damage-assessment product that helps an analyst decide **which areas to inspect first** after a disaster. It takes a before and an after
satellite image of an area, finds structures, grades visible damage in four levels (no damage, minor, major, destroyed), groups severe damage into ranked
area alerts and shows each alert with its evidence. The analyst confirms, dismisses or annotates every alert.

## 2. Intended users and setting

- Analysts and approving officers of disaster-management units (national, provincial and district), working with optical satellite imagery of 0.3 to
  1 m ground resolution, offline or with delayed internet.
- Each unit sees its own work and that of the units below it. Not a public service.

## 3. What the outputs mean

- A damage class describes what is **visible from above** in the images supplied, as judged by a model trained on the xBD dataset.
- An alert says "this area has a lot of severely damaged roof, in the model's judgement". It is a prompt to look, not a finding.
- Every alert starts as a **draft**. Nothing is published, sent or dispatched by the system.
- **"Not assessed"** means the system declined: an input check failed (blank or cloudy, unusual, too coarse, before image taken after the event) or
  most structures were below the review confidence. It is not "no damage": a person must look.

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
| Quality on disasters not seen in training is not yet measured for the approved model | Event-held-out test (E19) still to run; acceptance criterion AC-2 is not measured |
| Minor damage is the weakest class | F1 0.37 on test for the approved model (E15) |
| About 1 in 100 typical images is flagged as unusual and not assessed | Measured on 400 held-out xBD training images (5 flagged) |
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

Training and evaluation use xBD under its terms of use [to confirm]. Every upload records its source, its licence and who confirmed the right to process
it; camera and device metadata are removed from the files; uploaded images stay on the server, are used only for the requested assessment and can be
deleted at any time (and after the retention period, when one is set). No personal data are collected beyond account names in the review and audit logs.

## 8. Change control

A new default model, a threshold or a role's permissions changes only when a second administrator approves the request; the change and its reason
are written to the decision log (`gov.decisions`) and the audit log. A model that misses an acceptance criterion is released only with a written exception.
