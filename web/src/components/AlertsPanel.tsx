import { Alert, api, Assessment, BeforeInfo, CLASS_COLOUR, CLASS_LABEL, CLASSES, pct, tileNo, titleCase } from "../api";

interface Props { assessment: Assessment | null; loading: boolean; onAlert: (a: Alert) => void }

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

export default function AlertsPanel({ assessment: a, loading, onAlert }: Props) {
  if (!a || a.kind !== "area") {
    return <section><p className="empty-note">{loading ? "Detecting damage…" : "Select a tile or an upload to detect damage."}</p></section>;
  }
  const alerts = a.alerts ?? [];
  const high = alerts.filter((x) => x.severity === "high").length;
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
          <span className="value">{alerts.length}</span>
          <span className="text">{alerts.length === 1 ? "area alert" : "area alerts"}{alerts.length > 0 && <> · {high} high, {alerts.length - high} medium</>}</span>
        </div>
        {alerts.length > 0 ? (
          <table style={{ marginTop: 12 }}>
            <thead><tr><th>#</th><th>Severity</th><th className="num">Severe roof</th><th className="num">Share</th><th className="num">Extent</th></tr></thead>
            <tbody>
              {alerts.map((x, i) => (
                <tr key={x.alert_id} className="clickable" onClick={() => onAlert(x)} title={`${x.alert_id} · ${latlon(x.centroid_lat, x.centroid_lon)}`}>
                  <td>{i + 1}</td>
                  <td><span className={`sev sev-${x.severity}`}>{x.severity === "high" ? "High" : "Medium"}</span></td>
                  <td className="num">{area(x.severe_area_m2)}</td>
                  <td className="num">{pct(x.severe_share)}</td>
                  <td className="num">{area(x.area_m2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="empty-note" style={{ marginTop: 8 }}>No area meets the alert rule {upload ? "in this image" : "on this tile"}.</p>}
        <p className="meta" style={{ marginTop: 10 }}>
          An alert is raised for at least 250 m² of severely damaged roof with damage within 30 m; high when at least half
          of the building area there is severely damaged. Click a row to zoom; all alerts need analyst review.
        </p>
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
