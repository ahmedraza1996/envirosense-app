# Impact assessment (v1, 23 November 2026)

Control G7. Method after ISO/IEC 42005 (AI system impact assessment) and the content of a fundamental-rights impact assessment (EU AI Act
Article 27, which applies to public bodies deploying high-risk systems; used here as a checklist). Owner: principal investigator.
Review: every 6 months, after a serious incident, and before the system is used for a new region or hazard.

## 1. The system in one profile (OECD Framework for the Classification of AI Systems)
| Dimension | EnviroSense |
| --- | --- |
| People and planet | Users: analysts and approving officers of disaster-management units (NDMA, provincial PDMAs, district teams). Affected: residents of the imaged areas, whose homes are graded. Critical sector: emergency management. |
| Economic context | Public sector; decision support for inspection priorities; not a market product. |
| Data and input | Optical satellite images (0.3 to 1 m per pixel) of buildings; no personal data about people; training on the public xBD dataset (19 disasters). |
| AI model | Siamese U-Net (ResNet-34), supervised learning; fixed after release; calibrated confidence. |
| Task and output | Segmentation and damage grading; area alerts as drafts; a person confirms every one. Autonomy: none for actions. |

## 2. Risk tier
- **EU AI Act (benchmark):** emergency dispatch and its priority setting are high-risk (Annex III point 5(d); check the wording against the
  official text). EnviroSense excludes dispatch (`intended_use.md`), but ranking areas for inspection is close to it, so the system follows
  the high-risk requirements as good practice.
- **Pakistan:** no AI-specific law in force; PECA 2016 (security of systems and data) applies; the National AI Policy 2025 asks for responsible,
  human-overseen AI in public services.

## 3. Who can be harmed, and how
| Who | Harm | Cause | Controls |
| --- | --- | --- | --- |
| Residents of a damaged area | Area inspected late or not at all (missed damage) | Model misses damage; area not assessed; unusual imagery | P1 abstention shows "not assessed" instead of "no damage"; P2; M1 live precision; R07 per-hazard results |
| Residents of other areas | Resources sent to the wrong place (false alarm) | Over-detection; shadows, rubble look-alikes | Drafts only (A1); four-eyes (H1); dismiss with reason (H2); N2 incident on retraction |
| Communities in places unlike the training data (e.g. Pakistani building types, floods) | Systematically lower quality | xBD covers 19 events, mostly North America and Asia | V3 unseen-disaster score; I2 unusual-image check; limits stated in every export (E2) |
| People in the images | Privacy | Very-high-resolution imagery; camera metadata | No personal data used; I3 metadata removed; I5 retention; E3 own unit only |
| Analysts and officers | Over-trust in the system (automation bias) | Fast confirmations | H3 rubber-stamp measure; H4 oversight test |
| The public authority | Results it cannot explain or defend | Missing records | P3 provenance; F3 audit log; G4 decision log; G6 technical file |

## 4. Residual risk and decision
Residual risks are in the risk register (Risk register page). The system may be used for inspection triage by trained analysts, with every
alert confirmed by a second person, and must not be used for dispatch, safety, insurance or legal decisions. Re-assess before use in a
region or for a hazard not represented in the evaluation.
