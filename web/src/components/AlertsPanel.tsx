import { useEffect, useState } from "react";
import { Alert, AlertContext, api, Assessment, BeforeInfo, CLASS_COLOUR, CLASS_LABEL, CLASSES, Context, can, pct, REVIEW_LABEL, ReviewEntry, Reviews, ReviewStatus, tileNo, titleCase, User } from "../api";

interface Props {
  assessment: Assessment | null; loading: boolean; onAlert: (a: Alert) => void;
  alertId: string | null; reviews: Reviews | null; onReview: (alertId: string, status: ReviewStatus, note: string) => Promise<void>;
  context: Context | null; user: User;
}

const latlon = (lat: number, lon: number) =>
  `${Math.abs(lat).toFixed(5)}°${lat >= 0 ? "N" : "S"}, ${Math.abs(lon).toFixed(5)}°${lon >= 0 ? "E" : "W"}`;
const area = (m2: number) => (m2 >= 10000 ? `${(m2 / 10000).toFixed(1)} ha` : `${Math.round(m2).toLocaleString()} m²`);

function beforeSource(b: BeforeInfo) {
  if (b.kind === "upload") return "Uploaded with the after image";
  const n = b.tiles?.length ?? 0;
  return n ? `Archive, ${n} image${n === 1 ? "" : "s"}` : "None found in the archive";
}

function BeforeImage({ a }: { a: Assessment }) {
  const b = a.scene.before;
  if (!b) return null;
  const dates = [...new Set((b.tiles ?? []).map((t) => t.capture_date).filter(Boolean))].join(", ");
  return (
    <section>
      <h2>Before image</h2>
      <div className="pair">
        <figure><img src={api.imageUrl(a.pair_id, "pre")} alt="Before image, aligned to the after image" /><figcaption>Before{dates && `, ${dates}`}</figcaption></figure>
        <figure><img src={api.imageUrl(a.pair_id, "post")} alt="After image as uploaded" /><figcaption>After{a.scene.event_date && `, ${a.scene.event_date}`}</figcaption></figure>
      </div>
      <dl className="stats" style={{ marginTop: 12 }}>
        <dt>Source</dt><dd>{beforeSource(b)}</dd>
        <dt>Covers</dt><dd>{pct(b.coverage)} of the area</dd>
        <dt>Offset</dt><dd>{b.shift_m == null ? "not measured" : `${b.shift_m.toFixed(1)} m${b.corrected ? ", corrected" : ""}`}</dd>
        {b.method && b.method !== "phase correlation" && (
          <>
            <dt>Rotation</dt><dd>{(b.rotation_deg ?? 0) >= 0 ? "+" : ""}{(b.rotation_deg ?? 0).toFixed(2)}°</dd>
            <dt>Zoom</dt><dd>{(((b.scale ?? 1) - 1) * 100) >= 0 ? "+" : ""}{(((b.scale ?? 1) - 1) * 100).toFixed(1)}%</dd>
            <dt>Registration</dt><dd title={`${b.matches} matches, ${b.inliers} agree`}>{b.method === "sift" ? "SIFT" : "DISK + LightGlue"}, {b.inliers} features</dd>
          </>
        )}
      </dl>
      <p className="meta">
        {b.coverage === 0
          ? "No before image: buildings are located on the after image only, so completely destroyed buildings can be missed."
          : a.model.mode.includes("post-only")
            ? "Shown for comparison. This model reads the after image only, so completely destroyed buildings can be missed; the before + after model uses it to locate buildings."
            : "Buildings are located with the before image, damage is read from the after image."}
        {" "}Model: {a.model.mode}.
      </p>
      {(a.scene.notes ?? []).map((n) => <p key={n} className="meta note">{n}</p>)}
    </section>
  );
}

function ContextLines({ c }: { c: AlertContext }) {
  const near = Object.entries(c.within_1km).filter(([, n]) => n > 0).map(([k, n]) => `${n} ${k.toLowerCase()}${n === 1 ? "" : "s"}`).join(", ");
  return (
    <ul className="context">
      {c.flags.map((f) => <li key={f} className="flag">{f}</li>)}
      {c.nearest_hospital && <li>Nearest hospital: {c.nearest_hospital.name ?? "unnamed"}, {(c.nearest_hospital.distance_m / 1000).toFixed(1)} km</li>}
      {c.nearest_main_road && <li>Nearest main road: {c.nearest_main_road.distance_m} m ({c.nearest_main_road.class})</li>}
      {near && <li>Within 1 km: {near}</li>}
    </ul>
  );
}

function ReviewCard({ alert, index, entry, context, onReview, user }: {
  alert: Alert; index: number; entry: ReviewEntry; context: Context | null; user: User;
  onReview: (alertId: string, status: ReviewStatus, note: string) => Promise<void>;
}) {
  const [note, setNote] = useState(entry.note);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { setNote(entry.note); setErr(null); }, [alert.alert_id, entry.note]);
  const save = async (status: ReviewStatus) => {
    setErr(null);
    if ((status === "dismissed" || status === "retracted") && !note.trim()) { setErr(`A reason is required to ${status === "dismissed" ? "dismiss" : "retract"} an alert.`); return; }
    if (status === "pending" && entry.status === "proposed" && !note.trim()) { setErr("Say why the proposal is returned."); return; }
    setBusy(true);
    try { await onReview(alert.alert_id, status, note); } catch (e) { setErr(String(e)); } finally { setBusy(false); }
  };
  const c = context?.available ? context.alerts[alert.alert_id] : undefined;
  const officer = can(user, "approve");
  const mine = entry.proposed_by === user.username;
  const closed = entry.status === "dismissed" || entry.status === "retracted";
  return (
    <div className="review-card">
      <div className="review-head">
        <strong>Alert {index}</strong>
        <span className="scene-id">{alert.alert_id}</span>
        <span className={`status status-${entry.status}`}>{REVIEW_LABEL[entry.status]}</span>
      </div>
      <dl className="stats">
        <dt>Severely damaged roof</dt><dd>{area(alert.severe_area_m2)}</dd>
        <dt>Severe structures</dt><dd>{alert.severe} of {alert.structures}</dd>
        <dt>Location</dt><dd className="mono">{latlon(alert.centroid_lat, alert.centroid_lon)}</dd>
        {alert.low_confidence_structures != null && <><dt>Unsure structures</dt><dd>{alert.low_confidence_structures} of {alert.structures}{alert.low_confidence_share! >= 0.5 ? " (weak evidence: check first)" : ""}</dd></>}
      </dl>
      {c && <ContextLines c={c} />}
      {context?.available === null && <p className="meta">Looking up nearby facilities…</p>}
      {context?.available === false && <p className="meta" title={context.error}>Nearby facilities unavailable (OpenStreetMap not reachable).</p>}
      <label className="field-block">
        <span>Note (required to dismiss or retract)</span>
        <textarea value={note} maxLength={500} rows={2} placeholder="What you checked, who was told, why" onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="btn-row">
        {entry.status === "proposed" && officer && !mine && <button className="button primary" disabled={busy} onClick={() => save("confirmed")}>Confirm</button>}
        {entry.status === "proposed" && officer && !mine && <button className="button" disabled={busy} onClick={() => save("pending")}>Return to draft</button>}
        {(entry.status === "pending" || entry.status === "needs_info") && <button className="button primary" disabled={busy} onClick={() => save("proposed")}>Propose for confirmation</button>}
        {entry.status !== "confirmed" && !closed && entry.status !== "needs_info" && <button className="button" disabled={busy} onClick={() => save("needs_info")}>Needs information</button>}
        {entry.status !== "confirmed" && !closed && <button className="button" disabled={busy} onClick={() => save("dismissed")}>Dismiss</button>}
        {entry.status === "confirmed" && officer && <button className="button" disabled={busy} onClick={() => save("retracted")}>Retract</button>}
        {(closed || (entry.status === "needs_info")) && <button className="link" disabled={busy} onClick={() => { setNote(""); void save("pending"); }}>Reset to draft</button>}
      </div>
      {entry.status === "proposed" && (mine || !officer) && (
        <p className="meta">{mine ? "You proposed this alert; a different approving officer must confirm it." : "Waiting for an approving officer to confirm."}</p>
      )}
      {entry.reviewed_utc && <p className="meta">{REVIEW_LABEL[entry.status]} by {entry.reviewed_by} {entry.reviewed_utc} UTC</p>}
      {(entry.history?.length ?? 0) > 1 && (
        <details className="meta"><summary>History ({entry.history!.length})</summary>
          <ul>{entry.history!.map((h, i) => <li key={i}>{h.utc} UTC, {h.by}: {REVIEW_LABEL[h.status]}{h.note ? `, ${h.note}` : ""}</li>)}</ul>
        </details>
      )}
      {err && <p className="meta error-text">{err}</p>}
    </div>
  );
}

function ExportBar({ aid, hasDismissed }: { aid: string; hasDismissed: boolean }) {
  const [withDismissed, setWithDismissed] = useState(false);
  const include = withDismissed ? "pending,proposed,confirmed,needs_info,dismissed,retracted" : undefined;
  return (
    <div className="export-bar">
      <span className="subtle">Export alerts</span>
      <a className="link" href={api.exportUrl(aid, "alerts.geojson", include)} download>GeoJSON</a>
      <a className="link" href={api.exportUrl(aid, "csv", include)} download>CSV</a>
      <a className="link" href={api.exportUrl(aid, "structures.geojson")} download>Structures</a>
      {hasDismissed && <label className="inline-check"><input type="checkbox" checked={withDismissed} onChange={(e) => setWithDismissed(e.target.checked)} />include dismissed</label>}
    </div>
  );
}

export default function AlertsPanel({ assessment: a, loading, onAlert, alertId, reviews, onReview, context, user }: Props) {
  if (!a || a.kind !== "area") {
    return <section><p className="empty-note">{loading ? "Detecting damage…" : "Select a tile or an upload to detect damage."}</p></section>;
  }
  const alerts = a.alerts ?? [];
  const entryOf = (id: string): ReviewEntry => reviews?.alerts[id] ?? { status: "pending", note: "", reviewed_by: null, reviewed_utc: null };
  const counts = reviews?.counts;
  const selIndex = alerts.findIndex((x) => x.alert_id === alertId);
  const live = alerts.filter((x) => !["dismissed", "retracted"].includes(entryOf(x.alert_id).status));
  const high = live.filter((x) => x.severity === "high").length;
  const p = a.summary.predicted;
  const b = a.benchmark && Object.keys(a.benchmark).length ? a.benchmark : null;
  const upload = a.scene.source === "upload";
  return (
    <>
      <section>
        <h1>{upload ? a.scene.name : `${titleCase(a.scene.disaster)}, tile ${tileNo(a.pair_id)}`}</h1>
        <p className="meta">{upload ? `${titleCase(a.scene.disaster_type)} · uploaded imagery` : "Benchmark tile"} · no building inventory used</p>
        <div className="actions">
          <a className="button" href={api.reportUrl(a.id, "html")} target="_blank" rel="noreferrer">Situation report</a>
          <a className="link" href={api.reportUrl(a.id, "md")} download>Markdown</a>
        </div>
      </section>

      <section>
        <div className="headline">
          <span className="value">{live.length}</span>
          <span className="text">{live.length === 1 ? "area alert" : "area alerts"}{live.length > 0 && <> · {high} high, {live.length - high} medium</>}</span>
        </div>
        {alerts.length > 0 ? (
          <table style={{ marginTop: 12 }}>
            <thead><tr><th>#</th><th>Severity</th><th>Review</th><th className="num">Severe roof</th><th className="num">Share</th></tr></thead>
            <tbody>
              {alerts.map((x, i) => (
                <tr key={x.alert_id} className={`clickable ${x.alert_id === alertId ? "selected" : ""} ${["dismissed", "retracted"].includes(entryOf(x.alert_id).status) ? "dismissed" : ""}`}
                  onClick={() => onAlert(x)} title={`${x.alert_id} · ${latlon(x.centroid_lat, x.centroid_lon)}`}>
                  <td>{i + 1}</td>
                  <td><span className={`sev sev-${x.severity}`}>{x.severity === "high" ? "High" : "Medium"}</span></td>
                  <td><span className={`status status-${entryOf(x.alert_id).status}`}>{REVIEW_LABEL[entryOf(x.alert_id).status]}</span></td>
                  <td className="num">{area(x.severe_area_m2)}</td>
                  <td className="num">{pct(x.severe_share)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="empty-note" style={{ marginTop: 8 }}>No area meets the alert rule {upload ? "in this image" : "on this tile"}.</p>}
        {selIndex >= 0 && <ReviewCard alert={alerts[selIndex]} index={selIndex + 1} entry={entryOf(alerts[selIndex].alert_id)} context={context} onReview={onReview} user={user} />}
        <p className="meta" style={{ marginTop: 10 }}>
          An alert is raised for at least 250 m² of severely damaged roof with damage within 30 m; high when at least half
          of the building area there is severely damaged. Click a row to zoom and review it; alerts stay drafts until confirmed.
          {counts && alerts.length > 0 && <> Review: {counts.confirmed} confirmed, {counts.proposed} awaiting approval, {counts.needs_info} need information, {counts.pending} draft, {counts.dismissed} dismissed.</>}
        </p>
        {alerts.length > 0 && !can(user, "export") && <p className="meta">Exports need an approving officer.</p>}
        {alerts.length > 0 && can(user, "export") && <ExportBar aid={a.id} hasDismissed={((counts?.dismissed ?? 0) + (counts?.retracted ?? 0)) > 0} />}
        {(a.gates ?? []).some((g) => g.level === "warn") && (
          <ul className="context gates">{(a.gates ?? []).filter((g) => g.level === "warn").map((g) => <li key={g.code} className="flag">{g.message}</li>)}</ul>
        )}
        {(a.gates ?? []).filter((g) => g.level === "info" && g.code !== "DRAFT_ONLY").map((g) => <p key={g.code} className="meta">{g.message}</p>)}
        {a.gates && <p className="meta">Draft for analyst review: visible damage only, verify in the field. Not for dispatch or safety decisions.</p>}
      </section>

      {upload && <BeforeImage a={a} />}

      <section>
        <h2>Detected structures</h2>
        <table>
          <tbody>
            {[...CLASSES].reverse().map((c) => (
              <tr key={c}>
                <td><span className="class-cell"><i className="swatch" style={{ background: CLASS_COLOUR[c] }} />{CLASS_LABEL[c]}</span></td>
                <td className="num">{p[c]}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="meta" style={{ marginTop: 8 }}>
          {a.summary.buildings} structures found in the image. Touching buildings can merge into one structure, so these are
          not building counts.
        </p>
      </section>

      {b && (
        <section>
          <h2>Check against xBD (benchmark tile)</h2>
          <dl className="stats">
            <dt>xBD buildings found</dt><dd>{b.xbd_found} of {b.xbd_buildings} ({pct(b.recall)})</dd>
            <dt>Detections on buildings</dt><dd>{pct(b.precision)}</dd>
            {a.scene_metrics.xview2 && (<><dt>xView2 score</dt><dd>{a.scene_metrics.xview2.score.toFixed(2)}</dd></>)}
          </dl>
          <p className="meta">Used only to measure the model; the alerts above do not use xBD outlines.</p>
        </section>
      )}

      <section>
        <p className="provenance">
          {a.model.label} · {a.model.arch} · epoch {a.model.epoch + 1}<br />
          {a.model.checkpoint}<br />
          {a.model.git_commit.startsWith("not") ? "commit not recorded" : `commit ${a.model.git_commit.slice(0, 10)}`} · {a.created_utc} UTC
        </p>
      </section>
    </>
  );
}
