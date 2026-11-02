# Model cards: Siamese U-Net, E14 and E15 (v0.1, 2 November 2026)

Format after Mitchell et al. (2019), "Model cards for model reporting". Both models share one design; they differ in training. Single training run (seed) each.

## 1. Model details
- Type: Siamese U-Net. A shared ResNet-34 encoder (ImageNet weights, `segmentation_models_pytorch`) reads the before and after image; features are concatenated before the decoder; two heads: building localisation and four-class damage.
- Versions: **E14** `S_r34_paired_ext` (app id `unet_paired_ext`): 80 epochs in two stages (40 + 40), AdamW, cosine schedule, batch 4 over two GPUs. **E15** `S_r34_paired_mis` (`unet_paired_mis`): E14 plus 30 epochs with random shift, rotation and zoom of the before image in 60% of pairs, and the minor-damage class weight raised 1.5 times.
- Trained 29 October to 2 November 2026 (E13 and E14, then E15) by Ahmed Raza on two Tesla P40 GPUs. Code versions in `reports/experiments/`.
- Licences: libraries open source (PyTorch, segmentation_models_pytorch, Apache/MIT/BSD); data under xBD terms [to confirm].

## 2. Intended use
- Decision support for analysts triaging damage from optical satellite images (see `intended_use.md`). Not for the excluded uses listed there.

## 3. Factors
- Relevant: disaster type and event, region, image resolution and viewing angle, season and sun angle, registration of the two images, building size, class.
- Evaluated by: class (all), event (crop classifiers only so far), misregistration (shift, rotation, zoom). Not evaluated: sensor type, off-nadir angle, cloud, season.

## 4. Metrics
- xView2 score (0.3 x building-localisation F1 + 0.7 x harmonic mean of the four damage-class F1 values), per-class F1, robustness curves. Calibration not yet measured.

## 5. Evaluation data
- xBD official test (933 pairs) and hold (933 pairs) partitions; robustness on every sixth hold pair (156). Test and hold share events with training, so they are in-distribution; an unseen-event test for the U-Net is still to be done.

## 6. Training data
- xBD train and tier3 (9,168 pairs), 10% of pairs held out for checkpoint selection. Random 512 x 512 crops of the 1024 px images.

## 7. Quantitative analysis (xView2 score; flip TTA in brackets where run)

| | Test | Hold | Minor F1 (test) | Destroyed F1 (test) | Loc F1 (test) |
| --- | --- | --- | --- | --- | --- |
| E14 | 0.591 | 0.623 (0.625) | 0.30 | 0.67 | 0.787 |
| E15 | 0.625 (0.630) | 0.644 (0.648) | 0.37 | 0.64 | 0.776 |

Robustness, 156 hold tiles, score: stored 0.628 for both; shift 8 px: E14 0.579, E15 0.600; 16 px: 0.502 and 0.558; 32 px: 0.377 and 0.485; rotation 2 degrees: 0.498 and 0.562; 5 degrees: 0.358 and 0.482; zoom 3%: 0.519 and 0.571.
Effect of registration on these scores: experiment E15c (running).

## 8. Ethical considerations
- Missed severe damage and false alarms both have costs; the first is worse. Alerts are drafts that an analyst reviews.
- Quality is uneven across classes and events; minor damage is the weakest class; flood damage under intact roofs cannot be seen.
- Training data are from 19 events, mostly in North America and Asia; transfer to other settings is untested.

## 9. Caveats and recommendations
- Single seed; no confidence intervals; test and hold are not unseen events. E15 combines two changes, so the source of its gain is not separated.
- Use with registration on and with the position-offset status visible. Do not use outputs as field findings.
