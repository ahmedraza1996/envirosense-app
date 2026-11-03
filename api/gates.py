"""Input and result quality gates (control P3): conditions that must be visible to the analyst next to the alerts.

Each gate has a code, a level (info, warn) and a plain message. They never change a model output; they say how far to trust it.
Stored with the assessment and shown in the alert panel, the report and the exports.
"""
from .engines import review_confidence


def evaluate(scene: dict, model_id: str, approved: str | None, row: dict | None = None) -> list:
    g = []
    add = lambda code, level, msg: g.append({"code": code, "level": level, "message": msg})
    b = scene.get("before") or {}
    if scene.get("source") == "upload":
        if b.get("kind") not in (None, "upload", "archive"):
            add("BEFORE_SOURCE", "warn", f"Before image source: {b.get('kind')}.")
        cov = b.get("coverage")
        if cov is not None and cov < 0.5:
            add("LOW_BEFORE_COVERAGE", "warn", f"The before image covers only {100 * cov:.0f}% of the area; the rest was judged from the after image alone.")
        method = b.get("method")
        if method == "phase correlation" and not b.get("corrected"):
            add("REGISTRATION_SHIFT_ONLY", "warn", "Rotation and zoom between the two images could not be measured; only a shift was looked for.")
        elif method in ("disk+lightglue", "sift") and (b.get("rms_px") or 0) > 3:
            add("REGISTRATION_RESIDUAL", "warn", f"Registration residual is {b['rms_px']} px; alignment of the two images is uncertain.")
        resp = b.get("response")
        if resp is not None and resp < 0.05 and not b.get("corrected"):
            add("ALIGNMENT_UNMEASURED", "warn", "The two images differ too much to measure an offset; their georeferencing is used as given.")
        if (scene.get("pixel_size_m") or 0) > 1.2:
            add("COARSE_IMAGERY", "warn", f"Ground resolution is {scene['pixel_size_m']:.1f} m per pixel, coarser than the training imagery.")
    off = scene.get("geo_offset_m") or {}
    if not off.get("method"):
        add("POSITION_AS_FILED", "info", "Position on the street map is as given by the image's georeference; it was not checked against the street map.")
    else:
        add("POSITION_ADJUSTED", "info", f"Position moved {off.get('east', 0):+.1f} m east, {off.get('north', 0):+.1f} m north ({off['method']}).")
    if approved is None or model_id != approved:
        add("MODEL_NOT_APPROVED_DEFAULT", "warn", f"Model {model_id} is not the approved default model.")
    add("DRAFT_ONLY", "info", f"Model output awaiting analyst review. Structures below {int(review_confidence() * 100)}% confidence are marked for review.")
    return g
