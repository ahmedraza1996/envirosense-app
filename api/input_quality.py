"""Input quality of uploaded imagery: is the image like the ones the model was trained on, and how much of it shows nothing (blank or cloud)?

Six statistics of the after image (brightness, contrast, saturation, sharpness, blank share, cloud share) are compared with the range the same
statistics take on xBD training images (governance/reference_image_stats.json, written by app/scripts/reference_image_stats.py: 1st to 99th
percentile). An image with more statistics outside that range than the threshold `unusual_max_outside` allows is "unusual", and one with more blank
or cloud than `blank_max_share` cannot be assessed: the assessment then abstains instead of guessing (see service.area_record).

Also removes camera and device metadata (EXIF, XMP, IPTC, text chunks) from uploaded JPEG and PNG files without re-encoding them. GeoTIFF tags are
kept: their georeference is what places the image on the map.
"""
import json
import struct
from pathlib import Path

import cv2
import numpy as np

REFERENCE = Path(__file__).resolve().parents[1] / "governance" / "reference_image_stats.json"
# used only when the reference file is missing: wide ranges, so nothing is flagged on guesswork
FALLBACK = {"brightness": [20.0, 235.0], "contrast": [5.0, 95.0], "saturation": [3.0, 200.0], "sharpness": [1.0, 5000.0],
            "blank_share": [0.0, 0.5], "cloud_share": [0.0, 0.5]}
LABELS = {"brightness": "brightness", "contrast": "contrast", "saturation": "colour saturation", "sharpness": "sharpness",
          "blank_share": "blank share", "cloud_share": "cloud share"}
SIDE = 1024


def reference() -> dict:
    try:
        return json.loads(REFERENCE.read_text())["ranges"]
    except (OSError, ValueError, KeyError):
        return FALLBACK


def statistics(rgb: np.ndarray, valid: np.ndarray | None = None) -> dict:
    """The six statistics on a copy at most SIDE pixels a side. valid: pixels that hold image (outside the footprint is not blank, it is absent)."""
    h, w = rgb.shape[:2]
    k = min(1.0, SIDE / max(h, w))
    small = cv2.resize(np.ascontiguousarray(rgb), (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA) if k < 1 else rgb
    inside = np.ones(small.shape[:2], bool) if valid is None else cv2.resize(valid.astype(np.uint8), small.shape[1::-1], interpolation=cv2.INTER_NEAREST) > 0
    if inside.sum() < 100:
        return {"brightness": 0.0, "contrast": 0.0, "saturation": 0.0, "sharpness": 0.0, "blank_share": 1.0, "cloud_share": 0.0}
    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    grey = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    v, s, g = hsv[..., 2][inside].astype(np.float32), hsv[..., 1][inside].astype(np.float32), grey[inside].astype(np.float32)
    lap = cv2.Laplacian(grey, cv2.CV_32F)[inside]
    local_std = cv2.blur(grey.astype(np.float32) ** 2, (9, 9)) - cv2.blur(grey.astype(np.float32), (9, 9)) ** 2
    flat = np.sqrt(np.clip(local_std, 0, None))[inside] < 1.5            # no texture at all
    blank = flat & ((g < 8) | (g > 247))                                 # and black or burnt-out white: no-data padding, a saturated sensor
    cloud = (v > 215) & (s < 30) & ~blank                                # bright and colourless
    return {"brightness": float(g.mean()), "contrast": float(g.std()), "saturation": float(s.mean()), "sharpness": float(lap.var()),
            "blank_share": float(blank.mean()), "cloud_share": float(cloud.mean())}


def assess(rgb: np.ndarray, valid: np.ndarray | None, max_outside: float, blank_max: float) -> dict:
    st = statistics(rgb, valid)
    ref = reference()
    outside = [k for k, (lo, hi) in ref.items() if k in st and not lo <= st[k] <= hi]
    empty = st["blank_share"] + st["cloud_share"]
    unusual = len(outside) > max_outside
    level = "fail" if empty > blank_max or unusual else "warn" if outside else "ok"
    return {"stats": {k: round(v, 4) for k, v in st.items()}, "reference": ref, "outside": outside, "unusual": unusual,
            "empty_share": round(empty, 4), "level": level}


def describe(q: dict, max_outside: float, blank_max: float) -> list:
    """The input-quality lines of the upload's checks: [{name, level, text}]."""
    out = []
    empty = q["empty_share"]
    out.append({"name": "Blank or cloud", "level": "fail" if empty > blank_max else "warn" if empty > blank_max / 2 else "ok",
                "text": f"{empty:.0%} of the image is blank or cloud" + (f"; above {blank_max:.0%} the image is not assessed." if empty > blank_max else ".")})
    names = ", ".join(LABELS[k] for k in q["outside"])
    out.append({"name": "Unusual image", "level": "fail" if q["unusual"] else "warn" if q["outside"] else "ok",
                "text": "Brightness, contrast, colour and sharpness are within the range of the training images." if not q["outside"] else
                f"Outside the range of the training images: {names}." + (" The model was not trained on images like this, so it is not assessed."
                                                                          if q["unusual"] else " Check the result with care.")})
    return out


# ---- metadata ---------------------------------------------------------------------------------------------------

_JPEG_DROP = {0xE1: "EXIF/XMP", 0xED: "IPTC", 0xFE: "comment"}
_PNG_DROP = {b"tEXt": "text", b"zTXt": "text", b"iTXt": "text", b"eXIf": "EXIF", b"tIME": "time stamp"}


def _strip_jpeg(data: bytes) -> tuple[bytes, list]:
    if data[:2] != b"\xff\xd8":
        return data, []
    out, i, removed = bytearray(data[:2]), 2, []
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return data, []                                   # not a well-formed segment list: leave the file as it is
        marker = data[i + 1]
        if marker == 0xDA:                                    # start of scan: the compressed image follows, copy the rest unchanged
            out += data[i:]
            return bytes(out), removed
        if 0xD0 <= marker <= 0xD9 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        n = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i:i + 2 + n]
        if marker in _JPEG_DROP:
            removed.append(_JPEG_DROP[marker])
        else:
            out += seg
        i += 2 + n
    return data, []


def _strip_png(data: bytes) -> tuple[bytes, list]:
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return data, []
    out, i, removed = bytearray(data[:8]), 8, []
    while i + 8 <= len(data):
        n = struct.unpack(">I", data[i:i + 4])[0]
        kind = data[i + 4:i + 8]
        chunk = data[i:i + 12 + n]
        if kind in _PNG_DROP:
            removed.append(_PNG_DROP[kind])
        else:
            out += chunk
        i += 12 + n
        if kind == b"IEND":
            break
    return bytes(out), removed


def strip_metadata(path: Path) -> dict:
    """Remove camera and device metadata in place. Returns {"removed": [...], "kept": why} for the upload's checks."""
    ext = path.suffix.lower()
    if ext in (".tif", ".tiff"):
        return {"removed": [], "kept": "GeoTIFF tags kept: the georeference places the image on the map"}
    data = path.read_bytes()
    new, removed = _strip_jpeg(data) if ext in (".jpg", ".jpeg") else _strip_png(data) if ext == ".png" else (data, [])
    if removed:
        path.write_bytes(new)
    return {"removed": sorted(set(removed)), "kept": ""}
