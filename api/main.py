"""FastAPI app: scenes, models, assessments, evidence crops; serves the React build at /.

  uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000      (scripts/app.sh)
"""
import json
import re
import shutil
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import context, events, geoimage, report, reviews, service, uploads
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
    return [{"id": m["id"], "label": m["label"], "kind": m["kind"], "run": m["run_dir"].name, "test_score": m["test_score"]}
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
                        east: float | None = Form(None), north: float | None = Form(None),
                        before_west: float | None = Form(None), before_south: float | None = Form(None),
                        before_east: float | None = Form(None), before_north: float | None = Form(None)):
    """After image (+ optional before image) and metadata; processed in the background, poll GET /api/uploads/{id}.
    Plain PNG/JPEG need the after image's corner coordinates (degrees, north-up); GeoTIFFs carry their own."""
    models = service.models()
    if model_id not in models or models[model_id]["kind"] != "unet":
        raise HTTPException(400, "uploads need a full-image U-Net model")
    if disaster_type not in uploads.DISASTER_TYPES:
        raise HTTPException(400, f"disaster_type must be one of {', '.join(uploads.DISASTER_TYPES)}")
    if event_date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", event_date):
        raise HTTPException(400, "event_date must be YYYY-MM-DD")
    def corner_box(vals, what):
        if all(v is None for v in vals):
            return None
        w, s, e, n = vals
        if any(v is None for v in vals) or not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise HTTPException(400, f"{what}: corner coordinates need west < east and south < north, in degrees")
        return {"west": w, "south": s, "east": e, "north": n}

    is_tif = lambda f: Path(f.filename or "").suffix.lower() in (".tif", ".tiff")
    bounds = corner_box([west, south, east, north], "after image")
    before_bounds = corner_box([before_west, before_south, before_east, before_north], "before image")
    if bounds is None and not is_tif(after):
        raise HTTPException(400, "plain images need corner coordinates (west, south, east, north)")
    has_before = bool(before and before.filename)
    if has_before and before_bounds is None and not is_tif(before) and bounds is None:
        raise HTTPException(400, "a plain before image needs its own corner coordinates (before_west, before_south, before_east, before_north)")
    uid, d = uploads.new_folder()
    try:
        a = await save_upload(after, d, "after_input")
        b = await save_upload(before, d, "before_input") if has_before else None
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    uploads.create(a, {"name": name.strip()[:80] or "Untitled upload", "disaster_type": disaster_type,
                       "event_date": event_date or None, "model_id": model_id, "after_bounds": bounds,
                       "before_bounds": before_bounds}, b)
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


class UploadEdit(BaseModel):
    name: str | None = None
    disaster_type: str | None = None
    event_date: str | None = None


@app.patch("/api/uploads/{uid}")
def edit_upload(uid: str, body: UploadEdit):
    try:
        return uploads.update(uid, body.name, body.disaster_type, body.event_date)
    except KeyError:
        raise HTTPException(404, f"no upload {uid}")
    except uploads.imagery.ImageryError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/uploads/{uid}")
def delete_upload(uid: str):
    try:
        uploads.delete(uid)
    except KeyError:
        raise HTTPException(404, f"no upload {uid}")
    except uploads.imagery.ImageryError as e:
        raise HTTPException(409, str(e))
    return {"deleted": uid}


# ---- analyst review and export ------------------------------------------------------------------------------

def area_record_or_404(aid):
    rec = json.loads(stored(aid).read_text())
    if rec.get("kind") != "area":
        raise HTTPException(400, "alerts exist for area assessments only")
    return rec


class ReviewBody(BaseModel):
    status: str
    note: str = ""


@app.get("/api/assessments/{aid}/reviews")
def get_reviews(aid: str):
    rec = area_record_or_404(aid)
    r = reviews.load(aid)
    return {"alerts": {a["alert_id"]: reviews.entry(r, a["alert_id"]) for a in rec["alerts"]}, "counts": reviews.counts(rec, r)}


@app.put("/api/assessments/{aid}/alerts/{alert_id}/review")
def put_review(aid: str, alert_id: str, body: ReviewBody):
    rec = area_record_or_404(aid)
    try:
        e = reviews.set_review(aid, rec, alert_id, body.status, body.note)
    except KeyError:
        raise HTTPException(404, f"no alert {alert_id} in {aid}")
    except reviews.ReviewError as err:
        raise HTTPException(400, str(err))
    return {"alert_id": alert_id, **e, "counts": reviews.counts(rec, reviews.load(aid))}


def _include(include: str | None):
    return [x for x in (include or "").split(",") if x] or None


def _cached_context(aid):
    p = service.CACHE / "osm" / f"{aid}.json"
    return json.loads(p.read_text()) if p.exists() else None


@app.get("/api/assessments/{aid}/export.geojson")
def export_geojson(aid: str, layer: str = "alerts", include: str | None = None):
    """Alerts (default) or detected structures as GeoJSON (EPSG:4326). include = comma-separated review statuses;
    dismissed alerts are left out unless listed."""
    rec = area_record_or_404(aid)
    if layer not in ("alerts", "structures"):
        raise HTTPException(400, "layer must be alerts or structures")
    try:
        data = (reviews.alerts_geojson(rec, reviews.load(aid), _include(include), _cached_context(aid)) if layer == "alerts"
                else reviews.structures_geojson(rec))
    except reviews.ReviewError as e:
        raise HTTPException(400, str(e))
    return JSONResponse(data, media_type="application/geo+json",
                        headers={"Content-Disposition": f'attachment; filename="{layer}_{aid}.geojson"'})


@app.get("/api/assessments/{aid}/export.csv", response_class=PlainTextResponse)
def export_csv(aid: str, include: str | None = None):
    rec = area_record_or_404(aid)
    try:
        text = reviews.alerts_csv(rec, reviews.load(aid), _include(include), _cached_context(aid))
    except reviews.ReviewError as e:
        raise HTTPException(400, str(e))
    return PlainTextResponse(text, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="alerts_{aid}.csv"'})


@app.get("/api/assessments/{aid}/context")
def get_context(aid: str, refresh: bool = False):
    """Facilities and roads around the alerts (OpenStreetMap). available=null while it is fetched; poll again."""
    rec = area_record_or_404(aid)
    res = context.for_assessment(aid, rec, refresh)
    return {k: v for k, v in res.items() if not k.startswith("_")}


# ---- events ---------------------------------------------------------------------------------------------------

class EventJob(BaseModel):
    model_id: str
    limit: int = 10


def known_unet(model_id):
    m = service.models()
    if model_id not in m or m[model_id]["kind"] != "unet":
        raise HTTPException(400, "events use a full-image U-Net model")


@app.get("/api/events")
def get_events(model_id: str):
    known_unet(model_id)
    return events.list_events(model_id)


@app.get("/api/events/job")
def get_event_job():
    return events.job_state()


@app.get("/api/events/{disaster}")
def get_event(disaster: str, model_id: str):
    known_unet(model_id)
    try:
        return events.detail(disaster, model_id)
    except KeyError:
        raise HTTPException(404, f"unknown event {disaster}")


@app.post("/api/events/{disaster}/assess")
def assess_event(disaster: str, body: EventJob):
    """Assess up to `limit` tiles of the event that have no result yet, spread over the event (one at a time, in the background)."""
    known_unet(body.model_id)
    try:
        return events.start(disaster, body.model_id, min(body.limit, 50))
    except KeyError:
        raise HTTPException(404, f"unknown event {disaster}")


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
    rec = json.loads(stored(aid).read_text())
    keys = ("id", "kind", "scene", "model", "summary", "zones", "alerts", "alert_rule", "isolated_severe", "benchmark",
            "scene_metrics", "review_confidence_threshold", "has_damage_map")
    return {k: rec[k] for k in keys if k in rec}


@app.get("/api/assessments/{aid}/geo/{layer}")
def get_geo_layer(aid: str, layer: str):
    """North-up copy of the after / before image or the damage map for the street-map view (rotated geotransforms only)."""
    if layer not in ("pre", "post", "damage"):
        raise HTTPException(400, "layer must be pre, post or damage")
    rec = json.loads(stored(aid).read_text())
    sc = rec["scene"]
    if not sc.get("geo_bounds"):
        raise HTTPException(404, "this image is north-up already; use the ordinary image")
    out = service.CACHE / "geo" / f"{aid}_{layer}.webp"
    if not out.exists():
        import cv2
        out.parent.mkdir(parents=True, exist_ok=True)
        if layer == "damage":
            img = cv2.cvtColor(cv2.imread(str(service.STORE / f"{aid}_damage.png"), cv2.IMREAD_UNCHANGED), cv2.COLOR_BGRA2RGBA)
        else:
            img = service.record_image(rec, layer)
        out.write_bytes(geoimage.north_up(img, sc["geotransform"], sc["pixel_size_m"]))
    return FileResponse(out, media_type="image/webp")


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


class WebFiles(StaticFiles):
    """React build. index.html is never cached, so a new build shows on the next reload; hashed assets cache for good."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable" if path.startswith("assets/") else "no-cache"
        return resp


if WEB.exists():  # React build; the API routes above take precedence
    app.mount("/", WebFiles(directory=WEB, html=True), name="web")
