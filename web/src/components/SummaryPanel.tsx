import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, NOT_DETECTED_COLOUR, pct, tileNo, titleCase, Zone } from "../api";

interface Props { assessment: Assessment | null; loading: boolean; onZone: (z: Zone) => void; onBuilding: (id: string) => void }

export default function SummaryPanel({ assessment: a, loading, onZone, onBuilding }: Props) {
  if (!a) {
    return <section><p className="empty-note">{loading ? "Assessing tile…" : "Select a tile to see its assessment."}</p></section>;
  }
  const s = a.summary;
  const p = s.predicted;
  const v = s.vs_truth;
  const severe = p["major-damage"] + p.destroyed;
  const max = v.confusion ? Math.max(...v.confusion.flat(), 1) : 1;

  return (
    <>
      <section>
        <h1>{titleCase(a.scene.disaster)}, tile {tileNo(a.pair_id)}</h1>
        <p className="meta">{s.buildings} buildings · imagery {a.scene.pre_date} and {a.scene.post_date}</p>
        <div className="actions">
          <a className="button" href={api.reportUrl(a.id, "html")} target="_blank" rel="noreferrer">Situation report</a>
          <a className="link" href={api.reportUrl(a.id, "md")} download>Markdown</a>
        </div>
      </section>

      <section>
        <div className="headline">
          <span className="value">{severe}</span>
          <span className="text">buildings with major damage or destroyed</span>
        </div>
        <div className="dist" role="img" aria-label="Predicted damage distribution">
          {CLASSES.map((c) => p[c] > 0 && <span key={c} style={{ flex: p[c], background: CLASS_COLOUR[c] }} />)}
          {p["not-detected"] > 0 && <span style={{ flex: p["not-detected"], background: NOT_DETECTED_COLOUR }} />}
        </div>
        <table>
          <tbody>
            {[...CLASSES].reverse().map((c) => (
              <tr key={c}>
                <td><span className="class-cell"><i className="swatch" style={{ background: CLASS_COLOUR[c] }} />{CLASS_LABEL[c]}</span></td>
                <td className="num">{p[c]}</td>
                <td className="num subtle" style={{ width: 52 }}>{pct(p[c] / Math.max(s.buildings, 1))}</td>
              </tr>
            ))}
            {p["not-detected"] > 0 && (
              <tr><td><span className="class-cell"><i className="swatch" style={{ background: NOT_DETECTED_COLOUR }} />Not detected</span></td>
                <td className="num">{p["not-detected"]}</td><td className="num subtle">{pct(p["not-detected"] / s.buildings)}</td></tr>
            )}
          </tbody>
        </table>
        {s.needs_review > 0 && (
          <p className="review-line"><strong>{s.needs_review}</strong> flagged for review (confidence below {pct(a.review_confidence_threshold)}).</p>
        )}
      </section>

      <section>
        <h2>Priority areas</h2>
        {a.zones.length ? (
          <table>
            <thead><tr><th>#</th><th className="num">Destroyed</th><th className="num">Major</th><th className="num">Score</th></tr></thead>
            <tbody>
              {a.zones.slice(0, 8).map((z, i) => (
                <tr key={z.zone_id} className="clickable" onClick={() => onZone(z)} title={`${z.centroid_lat.toFixed(5)}, ${z.centroid_lon.toFixed(5)}`}>
                  <td>{i + 1}</td><td className="num">{z.counts.destroyed}</td>
                  <td className="num">{z.counts["major-damage"]}</td><td className="num">{z.priority}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : <p className="empty-note">No clusters of severe damage.</p>}
        {a.zones.length > 8 && <p className="meta">{a.zones.length - 8} smaller areas not listed.</p>}
        {a.isolated_severe.length > 0 && (
          <p className="meta" style={{ marginTop: 8 }}>
            {a.isolated_severe.length} isolated severe {a.isolated_severe.length === 1 ? "building" : "buildings"}:{" "}
            {a.isolated_severe.slice(0, 4).map((b, i) => (
              <span key={b.building_id}>{i > 0 && ", "}<button className="link" onClick={() => onBuilding(b.building_id)}>{b.building_id.slice(0, 8)}</button></span>
            ))}
          </p>
        )}
      </section>

      <section>
        <h2>Agreement with xBD labels</h2>
        {v.buildings_compared ? (
          <>
            <dl className="stats">
              <dt>Accuracy</dt><dd>{pct(v.accuracy, 1)}</dd>
              <dt>Macro-F1</dt><dd>{v.macro_f1_present_classes?.toFixed(2)}</dd>
              {a.scene_metrics.xview2 && (<><dt>xView2 score</dt><dd>{a.scene_metrics.xview2.score.toFixed(2)}</dd></>)}
              <dt>Compared</dt><dd>{v.buildings_compared}</dd>
            </dl>
            {v.confusion && (
              <table className="confusion">
                <thead><tr><th>xBD ↓ · model →</th>{CLASSES.map((c) => <th key={c}>{CLASS_LABEL[c].split(" ")[0]}</th>)}</tr></thead>
                <tbody>
                  {v.confusion.map((row, i) => (
                    <tr key={i}>
                      <td>{CLASS_LABEL[CLASSES[i]]}</td>
                      {row.map((n, j) => (
                        <td key={j} className="cell" style={{
                          background: n ? `rgba(36, 87, 166, ${0.08 + 0.5 * (n / max)})` : "transparent",
                          color: n / max > 0.6 ? "#fff" : n ? "var(--ink)" : "var(--ink-3)", fontWeight: i === j ? 600 : 400,
                        }}>{n}</td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : <p className="empty-note">No labelled buildings on this tile.</p>}
      </section>

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
