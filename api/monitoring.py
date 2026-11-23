"""Monitoring after release: is the system still doing what it was approved to do?

  live precision    of the most recent decided alerts (window: threshold live_precision_window), the share people confirmed; a retracted alert counts
                    as wrong. Overall, per model, per hazard type. Below live_precision_floor an incident is raised.
  abstention        how often the system declined to assess, and why (last 30 days)
  drift             share of uploads flagged unusual in the last 30 days against the 30 days before; growing by drift_ratio raises an incident
  review behaviour  confirmations decided in under rubber_stamp_seconds or without opening the evidence (possible rubber-stamping)
  audit chain       verified; a break raises an incident

`check()` runs the floors and raises incidents (one open incident per problem); it runs at start-up, when the monitoring page is opened and from the
compliance page.
"""
from ..db import semantic
from ..db.engine import one, rows, tx
from . import audit, incident_register

ACTOR = "system (monitoring)"
HAZARD = "COALESCE(u.disaster_type, 'benchmark')"


def _precision(c, window: int, where: str = "", **p) -> dict:
    rs = rows(c, "SELECT r.status, a.model_id, " + HAZARD + " AS hazard FROM wf.alert_reviews r JOIN core.assessments a ON a.id = r.assessment_id "
                 "LEFT JOIN ingest.uploads u ON u.id = a.upload_id WHERE r.status IN ('confirmed', 'dismissed', 'retracted') " + where +
                 " ORDER BY r.reviewed_at DESC NULLS LAST LIMIT :w", w=window, **p)
    conf = sum(r["status"] == "confirmed" for r in rs)
    return {"decided": len(rs), "confirmed": conf, "dismissed": sum(r["status"] == "dismissed" for r in rs),
            "retracted": sum(r["status"] == "retracted" for r in rs), "precision": round(conf / len(rs), 4) if rs else None, "rows": rs}


def live_precision() -> dict:
    window = int(semantic.threshold("live_precision_window"))
    floor = semantic.threshold("live_precision_floor")
    with tx() as c:
        overall = _precision(c, window)
        models = [r["model_id"] for r in rows(c, "SELECT DISTINCT a.model_id FROM wf.alert_reviews r JOIN core.assessments a ON a.id = r.assessment_id")]
        by_model = {m: {k: v for k, v in _precision(c, window, "AND a.model_id = :m", m=m).items() if k != "rows"} for m in models}
        hazards = [r["h"] for r in rows(c, "SELECT DISTINCT " + HAZARD + " AS h FROM wf.alert_reviews r JOIN core.assessments a ON a.id = r.assessment_id "
                                           "LEFT JOIN ingest.uploads u ON u.id = a.upload_id")]
        by_hazard = {h: {k: v for k, v in _precision(c, window, "AND " + HAZARD + " = :h", h=h).items() if k != "rows"} for h in hazards}
        reasons = rows(c, "SELECT r.note, r.reviewed_by, to_char(r.reviewed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI') AS utc FROM wf.alert_reviews r "
                          "WHERE r.status IN ('dismissed', 'retracted') ORDER BY r.reviewed_at DESC LIMIT 15")
    overall.pop("rows")
    below = overall["precision"] is not None and overall["decided"] >= window and overall["precision"] < floor
    return {"window": window, "floor": floor, "overall": overall, "by_model": by_model, "by_hazard": by_hazard, "dismissal_reasons": reasons,
            "below_floor": below, "enough_data": overall["decided"] >= window}


def abstention(days: int = 30) -> dict:
    with tx() as c:
        r = one(c, "SELECT count(*) AS total, count(*) FILTER (WHERE abstained) AS abstained FROM core.assessments WHERE created_at > now() - make_interval(days => :d)", d=days)
        why = rows(c, "SELECT reason, count(*) AS n FROM core.assessments, unnest(abstain_reasons) AS reason WHERE created_at > now() - make_interval(days => :d) "
                      "GROUP BY reason ORDER BY n DESC", d=days)
    return {"days": days, **r, "rate": round(r["abstained"] / r["total"], 4) if r["total"] else None, "reasons": why}


def drift() -> dict:
    ratio = semantic.threshold("drift_ratio")
    with tx() as c:
        cur = one(c, "SELECT count(*) AS n, count(*) FILTER (WHERE (input_quality->>'unusual')::boolean) AS unusual FROM ingest.uploads "
                     "WHERE created_at > now() - interval '30 days' AND input_quality ? 'unusual'")
        prev = one(c, "SELECT count(*) AS n, count(*) FILTER (WHERE (input_quality->>'unusual')::boolean) AS unusual FROM ingest.uploads "
                      "WHERE created_at <= now() - interval '30 days' AND created_at > now() - interval '60 days' AND input_quality ? 'unusual'")
        months = rows(c, "SELECT to_char(date_trunc('month', created_at), 'YYYY-MM') AS month, count(*) AS uploads, "
                         "count(*) FILTER (WHERE (input_quality->>'unusual')::boolean) AS unusual, "
                         "round(avg((input_quality->>'empty_share')::numeric), 3)::float AS empty_share, "
                         "round(avg((input_quality->'stats'->>'brightness')::numeric), 1)::float AS brightness "
                         "FROM ingest.uploads WHERE input_quality ? 'unusual' GROUP BY 1 ORDER BY 1 DESC LIMIT 12")
    share = lambda r: r["unusual"] / r["n"] if r["n"] else None
    s_cur, s_prev = share(cur), share(prev)
    rising = cur["n"] >= 5 and s_cur is not None and ((s_prev not in (None, 0) and s_cur / s_prev >= ratio) or (s_prev == 0 and s_cur >= 0.2))
    return {"ratio": ratio, "last_30_days": {**cur, "share": s_cur}, "previous_30_days": {**prev, "share": s_prev}, "rising": rising, "months": months}


def review_behaviour() -> dict:
    secs = semantic.threshold("rubber_stamp_seconds")
    with tx() as c:
        r = one(c, "SELECT count(*) AS confirmations, count(*) FILTER (WHERE seconds_to_decide IS NOT NULL OR evidence_viewed IS NOT NULL) AS measured, "
                   "count(*) FILTER (WHERE seconds_to_decide < :s) AS quick, count(*) FILTER (WHERE evidence_viewed IS FALSE) AS no_evidence, "
                   "count(*) FILTER (WHERE seconds_to_decide < :s OR evidence_viewed IS FALSE) AS flagged, "
                   "round(percentile_cont(0.5) WITHIN GROUP (ORDER BY seconds_to_decide)::numeric, 1)::float AS median_seconds "
                   "FROM wf.alert_review_events WHERE status = 'confirmed'", s=secs)
        people = rows(c, "SELECT actor, count(*) AS confirmations, count(*) FILTER (WHERE seconds_to_decide < :s OR evidence_viewed IS FALSE) AS flagged "
                         "FROM wf.alert_review_events WHERE status = 'confirmed' GROUP BY actor ORDER BY flagged DESC, confirmations DESC LIMIT 20", s=secs)
    return {"seconds": secs, **r, "share_flagged": round(r["flagged"] / r["measured"], 4) if r["measured"] else None, "by_reviewer": people}


def summary() -> dict:
    with tx() as c:
        approvals = one(c, "SELECT count(*) AS n FROM wf.approval_requests WHERE state = 'pending'")["n"]
    return {"live_precision": live_precision(), "abstention": abstention(), "drift": drift(), "review_behaviour": review_behaviour(),
            "incidents": incident_register.counts(), "pending_approvals": approvals}


def check(actor: str = ACTOR) -> list:
    """Run the floors; raise one incident per problem (a second run adds a note to the open one). Returns what was raised or noted."""
    raised = []
    lp = live_precision()
    if lp["below_floor"]:
        o = lp["overall"]
        raised.append(incident_register.open_incident(
            "model_quality", "high", f"Live precision {o['precision']:.0%} is below the floor of {lp['floor']:.0%}",
            f"Of the last {o['decided']} decided alerts, {o['confirmed']} were confirmed, {o['dismissed']} dismissed and {o['retracted']} retracted. "
            "Re-check the approved model on recent events before more alerts are issued.", actor, "check", dedup_key="live_precision"))
    d = drift()
    if d["rising"]:
        raised.append(incident_register.open_incident(
            "data_drift", "medium", "More uploaded images are unlike the training images",
            f"Unusual uploads: {d['last_30_days']['unusual']} of {d['last_30_days']['n']} in the last 30 days, against "
            f"{d['previous_30_days']['unusual']} of {d['previous_30_days']['n']} in the 30 days before.", actor, "check", dedup_key="drift"))
    rb = review_behaviour()
    if rb["measured"] >= 10 and (rb["share_flagged"] or 0) > 0.5:
        raised.append(incident_register.open_incident(
            "other", "medium", "Many confirmations look like rubber stamps",
            f"{rb['flagged']} of {rb['measured']} measured confirmations were decided in under {rb['seconds']:g} s or without opening the evidence.",
            actor, "check", dedup_key="rubber_stamp"))
    chain = audit.verify()
    if not chain["ok"]:
        raised.append(incident_register.open_incident(
            "audit_chain", "serious", f"Audit chain broken at entry {chain['first_bad_line']}",
            "An entry of the audit log was changed or removed outside the application.", actor, "check", dedup_key="audit_chain"))
    return raised
