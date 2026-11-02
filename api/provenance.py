"""Provenance of an assessment (controls P1, P2, A3): what went in, which model and code produced it, with which settings.

Stored inside the assessment record, so any alert, export or report can be traced back and a result can be reproduced or
explained from the record alone (traceability test of governance/control_matrix.md, X2).
"""
import hashlib
import platform
import sys
from pathlib import Path

_cache: dict = {}


def sha256_file(path: Path) -> str | None:
    """SHA-256 of a file, cached by size and modification time (checkpoints are hundreds of megabytes)."""
    try:
        st = path.stat()
    except OSError:
        return None
    key = (str(path), st.st_size, st.st_mtime_ns)
    if key not in _cache:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _cache[key] = h.hexdigest()
    return _cache[key]


def software() -> dict:
    out = {"python": platform.python_version()}
    for name in ("torch", "numpy", "cv2", "kornia", "segmentation_models_pytorch"):
        try:
            mod = __import__(name)
            out[name] = getattr(mod, "__version__", "unknown")
        except Exception:  # noqa: BLE001  a missing optional library is not an error here
            out[name] = None
    return out


def build(inputs: dict, run_dir: Path, thresholds: dict) -> dict:
    """inputs: {"after": path, "before": path or None or description}. Paths are hashed; other values are kept as given."""
    ins = {}
    for k, v in inputs.items():
        ins[k] = {"sha256": sha256_file(v)} if isinstance(v, Path) else {"source": v}
        if isinstance(v, Path):
            ins[k]["file"] = v.name
    return {"inputs": ins, "checkpoint": {"run": run_dir.name, "file": "best.pt", "sha256": sha256_file(run_dir / "best.pt")},
            "thresholds": thresholds, "software": software(), "python_executable": Path(sys.executable).name}
