"""FastAPI app: scenes, models, assessments, evidence crops; serves the React build at /.

  uv run uvicorn app.api.main:app --host 127.0.0.1 --port 8000      (scripts/app.sh)
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import service
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
    known_scene(pair_id)
    return FileResponse(image_jpeg(pair_id, phase), media_type="image/jpeg")


@app.post("/api/assess")
def run_assessment(req: AssessRequest):
    known_scene(req.pair_id)
    if req.model_id not in service.models():
        raise HTTPException(404, f"unknown model {req.model_id}")
    rec = service.assess(req.pair_id, req.model_id, req.force)
    return {k: rec[k] for k in ("id", "pair_id", "model", "summary", "created_utc")}


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
    return {k: rec[k] for k in ("id", "scene", "model", "summary", "zones", "isolated_severe", "scene_metrics",
                                "review_confidence_threshold", "has_damage_map")}


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


if WEB.exists():  # React build; the API routes above take precedence
    app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
