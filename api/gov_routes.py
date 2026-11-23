"""Routes of the governance screens: compliance and the technical file, the model registry, the data register, monitoring, incidents, the risk register,
the decision log and access reviews. Who may call each is a row of iam.route_policy (migration 0007)."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from . import auth, compliance, decisions, incident_register, model_registry, monitoring, risks

router = APIRouter()


def _call(fn, *a, **k):
    try:
        return fn(*a, **k)
    except incident_register.IncidentError as e:
        raise HTTPException(e.status, str(e))
    except (risks.RiskError, ValueError) as e:
        raise HTTPException(400, str(e))
    except KeyError as e:
        raise HTTPException(404, f"not found: {e}")


# ---- compliance ---------------------------------------------------------------------------------------------------

@router.get("/api/gov/controls")
def get_controls():
    return compliance.register()


@router.get("/api/gov/frameworks")
def get_frameworks():
    reg = compliance.register()
    return {"frameworks": reg["frameworks"], "checked_utc": reg["checked_utc"]}


@router.get("/api/gov/technical-file.md", response_class=PlainTextResponse)
def get_technical_file():
    return PlainTextResponse(compliance.technical_file(), media_type="text/markdown",
                             headers={"Content-Disposition": 'attachment; filename="envirosense_technical_file.md"'})


@router.post("/api/gov/checks")
def run_checks():
    """Run the monitoring floors now (they also run at start-up and when the monitoring page opens)."""
    return {"raised": monitoring.check(), "controls": compliance.register()["counts"]}


# ---- model registry -----------------------------------------------------------------------------------------------

@router.get("/api/gov/models")
def get_models():
    return {"models": model_registry.registry(), "criteria": model_registry.criteria()}


@router.get("/api/gov/models/{model_id}")
def get_model(model_id: str):
    return _call(model_registry.detail, model_id)


@router.get("/api/gov/models/{model_id}/card")
def get_card(model_id: str):
    return _call(model_registry.card, model_id)


# ---- data, decisions ----------------------------------------------------------------------------------------------

@router.get("/api/gov/data")
def get_data():
    return compliance.data_register()


@router.get("/api/gov/decisions")
def get_decisions(limit: int = 300):
    return decisions.list_decisions(limit)


# ---- monitoring and incidents -------------------------------------------------------------------------------------

@router.get("/api/gov/monitoring")
def get_monitoring():
    monitoring.check()
    return monitoring.summary()


class NewIncident(BaseModel):
    kind: str
    severity: str
    title: str
    description: str = ""
    assessment: str | None = None
    alert_id: str | None = None


class IncidentAction(BaseModel):
    note: str = ""
    severity: str | None = None
    cause: str = ""
    resolution: str = ""


@router.get("/api/gov/incidents")
def get_incidents(state: str | None = None):
    return incident_register.list_incidents(auth.current(), state)


@router.get("/api/gov/incidents/{iid}")
def get_incident(iid: int):
    return _call(incident_register.get, iid, auth.current())


@router.post("/api/gov/incidents")
def post_incident(body: NewIncident):
    u = auth.current()
    links = {k: v for k, v in (("assessment", body.assessment), ("alert_id", body.alert_id)) if v}
    return _call(incident_register.open_incident, body.kind, body.severity, body.title, body.description, u["username"], "person", u["unit"], links)


@router.post("/api/gov/incidents/{iid}/assess")
def assess_incident(iid: int, body: IncidentAction):
    return _call(incident_register.assess, iid, auth.current(), body.note, body.severity)


@router.post("/api/gov/incidents/{iid}/note")
def note_incident(iid: int, body: IncidentAction):
    return _call(incident_register.add_note, iid, auth.current(), body.note)


@router.post("/api/gov/incidents/{iid}/close")
def close_incident(iid: int, body: IncidentAction):
    return _call(incident_register.close, iid, auth.current(), body.cause, body.resolution)


@router.post("/api/gov/incidents/{iid}/reopen")
def reopen_incident(iid: int, body: IncidentAction):
    return _call(incident_register.reopen, iid, auth.current(), body.note)


# ---- risks --------------------------------------------------------------------------------------------------------

class RiskChange(BaseModel):
    reason: str
    stage: str | None = None
    risk: str | None = None
    cause: str | None = None
    likelihood: int | None = None
    severity: int | None = None
    controls: list[str] | None = None
    planned: str | None = None
    owner: str | None = None
    residual: str | None = None
    status: str | None = None
    next_review: str | None = None


@router.get("/api/gov/risks")
def get_risks():
    return risks.list_risks()


@router.put("/api/gov/risks/{rid}")
def put_risk(rid: str, body: RiskChange):
    ch = body.model_dump(exclude={"reason"})
    return _call(risks.update, rid, ch, auth.actor(), body.reason)


@router.post("/api/gov/risks")
def post_risk(body: RiskChange):
    return _call(risks.create, body.model_dump(exclude={"reason"}), auth.actor(), body.reason)


# ---- access reviews -----------------------------------------------------------------------------------------------

class AccessReview(BaseModel):
    username: str
    decision: str
    note: str = ""


@router.get("/api/gov/access-reviews")
def get_access_reviews():
    return compliance.access_reviews(auth.current())


@router.post("/api/gov/access-reviews")
def post_access_review(body: AccessReview):
    return _call(compliance.review_access, body.username, body.decision, body.note, auth.current())
