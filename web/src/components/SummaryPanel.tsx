import { Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, NOT_DETECTED_COLOUR, pct, Zone } from "../api";

interface Props { assessment: Assessment | null; loading: boolean; onZone: (z: Zone) => void; onBuilding: (id: string) => void }

export default function SummaryPanel({ assessment: a, loading, onZone, onBuilding }: Props) {
  if (!a) return <div className="ph"><h2>Summary</h2><div className="sub">{loading ? "Assessing…" : "No scene assessed yet"}</div></div>;
  const s = a.summary;
  const p = s.predicted;
  const v = s.vs_truth;
  const x = a.scene_metrics.xview2;
  return (
    <>
      <div className="ph">
        <h2>{a.scene.disaster} · damage summary</h2>
        <div className="sub">{a.pair_id} · before {a.scene.pre_date ?? "?"} · after {a.scene.post_date ?? "?"}</div>
      </div>

      <div className="sec">
        <div className="kgrid">
          <div className="kpi"><div className="v" style={{ color: "var(--accent)" }}>{s.assessed}</div><div className="k">Assessed of {s.buildings}</div></div>
          <div className="kpi"><div className="v">{p.destroyed}</div><div className="k"><span className="sw" style={{ background: CLASS_COLOUR.destroyed }} />Destroyed</div></div>
          <div className="kpi"><div className="v">{p["major-damage"]}</div><div className="k"><span className="sw" style={{ background: CLASS_COLOUR["major-damage"] }} />Major</div></div>
          <div className="kpi"><div className="v">{p["minor-damage"]}</div><div className="k"><span className="sw" style={{ background: CLASS_COLOUR["minor-damage"] }} />Minor</div></div>
          <div className="kpi"><div className="v">{p["no-damage"]}</div><div className="k"><span className="sw" style={{ background: CLASS_COLOUR["no-damage"] }} />No damage</div></div>
          <div className="kpi"><div className="v" style={{ color: "var(--warn)" }}>{s.needs_review}</div><div className="k">Needs review</div></div>
        </div>
        <div className="bar big">
          {CLASSES.map((c) => <span key={c} style={{ flex: p[c], background: CLASS_COLOUR[c] }} />)}
          <span style={{ flex: p["not-detected"], background: NOT_DETECTED_COLOUR }} />
        </div>
        <div className="between" style={{ marginTop: 10 }}>
          <span className="muted">Major or destroyed, among confidently assessed</span><b>{pct(s.severe_share, 1)}</b>
        </div>
        <div className="note">Coverage {pct(s.coverage, 1)}; review threshold: confidence below {pct(a.review_confidence_threshold)}{p["not-detected"] ? ` or not detected (${p["not-detected"]})` : ""}.</div>
      </div>

      <div className="sec">
        <div className="lbl">Check against xBD labels</div>
        {v.buildings_compared ? (
          <>
            <div className="between"><span className="muted">Buildings compared</span><b>{v.buildings_compared}</b></div>
            <div className="between"><span className="muted">Accuracy</span><b>{pct(v.accuracy, 1)}</b></div>
            <div className="between"><span className="muted">Macro-F1 (classes present)</span><b>{v.macro_f1_present_classes?.toFixed(3)}</b></div>
            {x && <div className="between"><span className="muted">xView2 pixel score (scene)</span><b>{x.score.toFixed(3)}</b></div>}
            {v.confusion && (
              <table className="t" style={{ marginTop: 8 }}>
                <thead><tr><th>xBD \ model</th>{CLASSES.map((c) => <th key={c} className="n">{CLASS_LABEL[c].slice(0, 5)}</th>)}</tr></thead>
                <tbody>{v.confusion.map((row, i) => (
                  <tr key={i}><td>{CLASS_LABEL[CLASSES[i]]}</td>{row.map((n, j) => (
                    <td key={j} className="n" style={{ color: i === j ? "var(--text)" : n ? "var(--muted)" : "var(--dim)", fontWeight: i === j ? 700 : 400 }}>{n}</td>
                  ))}</tr>
                ))}</tbody>
              </table>
            )}
          </>
        ) : <div className="dim">No labelled buildings to compare.</div>}
      </div>

      <div className="sec">
        <div className="lbl">Priority zones</div>
        {a.zones.length ? (
          <table className="t">
            <thead><tr><th>Zone</th><th className="n">Destr.</th><th className="n">Major</th><th className="n">Minor</th><th className="n">Priority</th></tr></thead>
            <tbody>{a.zones.map((z) => (
              <tr key={z.zone_id} className="click" onClick={() => onZone(z)} title={`${z.centroid_lat.toFixed(5)}, ${z.centroid_lon.toFixed(5)}`}>
                <td><b>{z.zone_id}</b></td><td className="n">{z.counts.destroyed}</td><td className="n">{z.counts["major-damage"]}</td>
                <td className="n">{z.counts["minor-damage"]}</td><td className="n">{z.priority}</td>
              </tr>
            ))}</tbody>
          </table>
        ) : <div className="dim">No clusters of major/destroyed buildings.</div>}
        {a.isolated_severe.length > 0 && (
          <div style={{ marginTop: 8 }}>
            <div className="muted" style={{ fontSize: 12 }}>{a.isolated_severe.length} isolated severe building(s), kept for review:</div>
            <div className="mono" style={{ marginTop: 4 }}>
              {a.isolated_severe.slice(0, 8).map((b) => (
                <span key={b.building_id} style={{ cursor: "pointer", marginRight: 8, color: CLASS_COLOUR[b.predicted_class] }} onClick={() => onBuilding(b.building_id)}>
                  {b.building_id.slice(0, 8)}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="note" style={{ marginTop: 6 }}>Clusters of major/destroyed within 30 m (DBSCAN). Priority = 3×destroyed + 2×major + ½×minor. Click a zone to zoom.</div>
      </div>

      <div className="sec" style={{ borderBottom: 0 }}>
        <div className="lbl">Model</div>
        <div className="mono muted">
          {a.model.label} · {a.model.mode}<br />
          {a.model.arch} · run {a.model.run} · epoch {a.model.epoch + 1}<br />
          {a.model.checkpoint}<br />
          commit {a.model.git_commit.slice(0, 40)}<br />
          assessed {a.created_utc} UTC
        </div>
      </div>
    </>
  );
}
