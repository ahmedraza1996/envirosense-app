"""FastAPI app: scenes, models, assessments, evidence crops; serves the React build at /.

  uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000      (scripts/app.sh)
"""
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import report, service, uploads
from .scenes import catalogue, image_jpeg, scene

app = FastAPI(title="EnviroSense damage assessment", version="0.1")
WEB = Path(__file__).resolve().parents[1] / "web" / "dist"


class AssessRequest(BaseModel):
    pair_id: str
    model_id: str = "clf_B"
    force: bool = False


def known_scene(pair_id):
    try:
        return scene(pair_id)
    except KeyError:
        raise HTTPException(404, f"unknown scene {pair_id}")


@app.get("/api/health")
def health():
    return {"ok": True, "models": list(service.models())}


@app.get("/api/models")
def list_models():
    return [{"id": m["id"], "label": m["label"], "kind": m["kind"], "run": m["run_dir"].name}
            for m in service.models().values()]


@app.get("/api/scenes")
def list_scenes(split: str = "hold", disaster: str | None = None):
    df = catalogue()
    df = df[df.split == split]
    if disaster:
        df = df[df.disaster == disaster]
    return {"disasters": sorted(catalogue()[catalogue().split == split].disaster.unique().tolist()),
            "scenes": df.sort_values(["disaster", "pair_id"]).to_dict(orient="records")}


@app.get("/api/scenes/{pair_id}")
def get_scene(pair_id: str):
    return known_scene(pair_id)


@app.get("/api/scenes/{pair_id}/image/{phase}")
def get_image(pair_id: str, phase: str):
    if phase not in ("pre", "post"):
        raise HTTPException(400, "phase must be pre or post")
    if uploads.is_upload(pair_id):  # uploads: the images on the upload's own grid (before = aligned mosaic)
        try:
            path = uploads.folder(pair_id) / f"{phase}.jpg"
        except KeyError:
            path = None
        if not path or not path.exists():
            raise HTTPException(404, f"no {phase} image for {pair_id}")
        return FileResponse(path, media_type="image/jpeg")
    known_scene(pair_id)
    return FileResponse(image_jpeg(pair_id, phase), media_type="image/jpeg")


async def save_upload(f: UploadFile, dest_dir: Path, stem: str) -> Path:
    ext = Path(f.filename or "").suffix.lower()
    if ext not in uploads.EXTENSIONS:
        raise HTTPException(400, f"{f.filename}: use GeoTIFF, PNG or JPEG")
    dest, size = dest_dir / f"{stem}{ext}", 0
    with dest.open("wb") as out:
        while chunk := await f.read(1 << 20):
            size += len(chunk)
            if size > uploads.MAX_BYTES:
                raise HTTPException(413, f"{f.filename} is larger than {uploads.MAX_BYTES >> 20} MB")
            out.write(chunk)
    return dest


@app.post("/api/uploads")
async def create_upload(after: UploadFile = File(...), before: UploadFile | None = File(None),
                        name: str = Form(...), disaster_type: str = Form("other"), event_date: str = Form(""),
                        model_id: str = Form("unet_early"), west: float | None = Form(None), south: float | None = Form(None),
                        east: float | None = Form(None), north: float | None = Form(None)):
    """After image (+ optional before image) and metadata; processed in the background, poll GET /api/uploads/{id}.
    Plain PNG/JPEG need the after image's corner coordinates (degrees, north-up); GeoTIFFs carry their own."""
    models = service.models()
    if model_id not in models or models[model_id]["kind"] != "unet":
        raise HTTPException(400, "uploads need a full-image U-Net model")
    if disaster_type not in uploads.DISASTER_TYPES:
        raise HTTPException(400, f"disaster_type must be one of {', '.join(uploads.DISASTER_TYPES)}")
    if event_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        raise HTTPException(400, "event_date must be YYYY-MM-DD")
    corners = [west, south, east, north]
    bounds = None
    if any(v is not None for v in corners):
        if any(v is None for v in corners) or not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise HTTPException(400, "corner coordinates need west < east and south < north, in degrees")
        bounds = {"west": west, "south": south, "east": east, "north": north}
    elif Path(after.filename or "").suffix.lower() not in (".tif", ".tiff"):
        raise HTTPException(400, "plain images need corner coordinates (west, south, east, north)")
    uid, d = uploads.new_folder()
    try:
        a = await save_upload(after, d, "after_input")
        b = await save_upload(before, d, "before_input") if before and before.filename else None
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    uploads.create(a, {"name": name.strip()[:80] or "Untitled upload", "disaster_type": disaster_type,
                       "event_date": event_date or None, "model_id": model_id, "after_bounds": bounds,
                       "before_bounds": None}, b)
    return uploads.info(uid)


@app.get("/api/uploads")
def get_uploads():
    return uploads.list_uploads()


@app.get("/api/uploads/{uid}")
def get_upload(uid: str):
    try:
        return uploads.info(uid)
    except KeyError:
        raise HTTPException(404, f"no upload {uid}")


@app.post("/api/assess")
def run_assessment(req: AssessRequest):
    known_scene(req.pair_id)
    if req.model_id not in service.models():
        raise HTTPException(404, f"unknown model {req.model_id}")
    rec = service.assess(req.pair_id, req.model_id, req.force)
    return {k: rec[k] for k in ("id", "pair_id", "model", "summary", "created_utc")}


@app.post("/api/assess-area")
def run_area_assessment(req: AssessRequest):
    """Footprint-free mode: structures detected from the image, one alert per cluster of severe damage."""
    known_scene(req.pair_id)
    if req.model_id not in service.models():
        raise HTTPException(404, f"unknown model {req.model_id}")
    if service.models()[req.model_id]["kind"] != "unet":
        raise HTTPException(400, "area alerts need a full-image U-Net model")
    rec = service.assess_area(req.pair_id, req.model_id, req.force)
    return {"id": rec["id"], "pair_id": rec["pair_id"], "model": rec["model"], "alerts": len(rec["alerts"]),
            "summary": rec["summary"], "created_utc": rec["created_utc"]}


@app.get("/api/assessments/{aid}/features/{fid}/crop/{phase}")
def get_feature_crop(aid: str, fid: str, phase: str):
    if phase not in ("pre", "post"):
        raise HTTPException(400, "phase must be pre or post")
    stored(aid)
    try:
        return Response(service.feature_crop(aid, fid, phase), media_type="image/png")
    except StopIteration:
        raise HTTPException(404, f"no feature {fid} in {aid}")


def stored(aid):
    path = service.STORE / f"{aid}.json"
    if not path.exists():
        raise HTTPException(404, f"no assessment {aid}; POST /api/assess first")
    return path


@app.get("/api/assessments/{aid}")
def get_assessment(aid: str):
    return FileResponse(stored(aid), media_type="application/json")


@app.get("/api/assessments/{aid}/summary")
def get_summary(aid: str):
    import json
    rec = json.loads(stored(aid).read_text())
    keys = ("id", "kind", "scene", "model", "summary", "zones", "alerts", "alert_rule", "isolated_severe", "benchmark",
            "scene_metrics", "review_confidence_threshold", "has_damage_map")
    return {k: rec[k] for k in keys if k in rec}


@app.get("/api/assessments/{aid}/damage-map")
def get_damage_map(aid: str):
    path = service.STORE / f"{aid}_damage.png"
    if not path.exists():
        raise HTTPException(404, "this model has no pixel damage map")
    return FileResponse(path, media_type="image/png")


@app.get("/api/scenes/{pair_id}/buildings/{uid}/crop/{phase}")
def get_crop(pair_id: str, uid: str, phase: str):
    if phase not in ("pre", "post"):
        raise HTTPException(400, "phase must be pre or post")
    known_scene(pair_id)
    try:
        return Response(service.building_crop(pair_id, uid, phase), media_type="image/png")
    except StopIteration:
        raise HTTPException(404, f"no building {uid} in {pair_id}")


def report_or_404(fn, aid):
    try:
        return fn(aid)
    except FileNotFoundError:
        raise HTTPException(404, f"no assessment {aid}; POST /api/assess first")
    except report.ReportError as e:  # internal inconsistency: never publish a report whose numbers don't add up
        raise HTTPException(500, str(e))


@app.get("/api/assessments/{aid}/report.md", response_class=PlainTextResponse)
def get_report_md(aid: str):
    text = report_or_404(report.markdown, aid)
    return PlainTextResponse(text, media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="sitrep_{aid}.md"'})


@app.get("/api/assessments/{aid}/report.html", response_class=HTMLResponse)
def get_report_html(aid: str):
    return HTMLResponse(report_or_404(report.to_html, aid))


@app.get("/api/assessments/{aid}/report-map.png")
def get_report_map(aid: str):
    return Response(report_or_404(report.map_png, aid), media_type="image/png")


if WEB.exists():  # React build; the API routes above take precedence
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
