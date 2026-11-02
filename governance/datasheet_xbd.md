# Datasheet: xBD as used in EnviroSense (v0.1, 2 November 2026)

Format after Gebru et al. (2021), "Datasheets for datasets". Items marked [to confirm] could not be established from the project files and need the dataset's own documentation or the supervisor.
Source of the facts below: `reports/audit_xbd.md` (audit run 25 October 2026 on the challenge release) and the xBD paper (Gupta et al., 2019).

## 1. Motivation
- Purpose: a benchmark for building-damage assessment from before and after satellite images (xView2 challenge).
- Creators and funders: xBD authors; challenge run by the Defense Innovation Unit [to confirm funder details].

## 2. Composition
- 22,068 images of 1024 x 1024 pixels in 11,034 before/after pairs; pixel size 0.39 to 0.50 m (from the geotransform file); 19 disaster events.
- 425,368 buildings counted once; 850,736 annotations (a building is annotated in both images).
- Four damage levels on the post image: no damage, minor, major, destroyed; plus "un-classified" (14,011 buildings, 3.3%), which is masked, never counted as undamaged.
- Class balance among classified buildings: 76.1% no damage, 9.0% minor, 7.3% major, 7.7% destroyed.
- Partitions: train (2,799 pairs), tier3 (6,369), test (933), hold (933). Train, test and hold share the same 10 events; tier3 holds 9 other events. Fires dominate tier3 (4,592 of 6,369 pairs). Only one earthquake event (Mexico, 193 pairs).
- Building size: median 650 px2 (about 25 x 25 px), 10th percentile 134 px2, 90th percentile 1,920 px2.
- Data quality found: 80 invalid polygons (0.009%), 5,772 polygons crossing the image border (0.68%); identical building sets in the before and after file of every pair; no missing or mis-sized images.
- Georeferencing: the geotransforms file and the per-label longitude/latitude polygons disagree (scale 0 to 12%, origin 0.3 to 12.6 m, median about 9 m in 14 sampled images). Which is correct is unresolved; against OpenStreetMap, one tile showed about 20 m between the geotransform and the roofs (experiment X8 will measure more tiles).
- Labels fit the before image (median 0.78 px) better than the after image (median 2.57 px): experiment E14c.
- No personal data in the imagery at this resolution is intended; faces and plates are not resolvable. Images show buildings and land.

## 3. Collection process
- Satellite imagery from commercial providers, released for the challenge; building outlines and damage labels annotated by humans with a joint damage scale [to confirm annotator process and agreement from the paper].
- Time span and sensors per event: see the dataset's metadata (capture dates are in the label files).

## 4. Preprocessing in this project
- Archives verified by SHA1 (`configs/xbd_sha1.txt`, `scripts/verify_xbd.sh`).
- Unclassified buildings masked; invalid polygons repaired or dropped; building crops with context padding (128 px store); target masks for full-image models (background 0, damage 1 to 4 in masks; classes 0 to 3 in crop classifiers).
- Splits: official partitions kept untouched for benchmark reporting; a separate event-grouped split for the unseen-event protocol; checkpoint selection on 10% held-out pairs of the training events.

## 5. Uses
- Intended: research and teaching on building-damage assessment; prototype triage with human review.
- Not suitable for: operational decisions without field verification; hazards and regions far from the 19 events; sensors very different from the source imagery; flood damage under intact roofs; drone imagery.
- Known risks: unequal class and event distribution (models are weakest on minor damage and on rare hazards); label noise in the intermediate classes.

## 6. Distribution and terms
- Terms of use and licence: [to confirm from the dataset release; the ideation deck states non-commercial research use]. No redistribution of the data; only derived results are kept in the repositories.

## 7. Maintenance
- Static release; this project does not modify the source files. Derived data (`data/xbd_crops`, targets) are rebuilt by the scripts in `src/`. Corrections to this datasheet are recorded in `decision_log.md`.
