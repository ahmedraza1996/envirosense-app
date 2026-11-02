import { useEffect, useState } from "react";
import L from "leaflet";
import { MapContainer, Polygon, TileLayer, Tooltip, useMap } from "react-leaflet";
import { api, CLASS_COLOUR, EventDetail, EventJob, EventSummary, EventTile, ModelInfo, titleCase } from "../api";

// Event view: every tile of one disaster on the street map with its alerts, and a ranking of the tiles.

const area = (m2: number) => (m2 >= 10000 ? `${(m2 / 10000).toFixed(1)} ha` : `${Math.round(m2).toLocaleString()} m²`);
const ll = (ring: [number, number][]) => ring.map(([lon, lat]) => L.latLng(lat, lon));

export function EventList({ events, selected, onSelect, model }: { events: EventSummary[]; selected: string | null; onSelect: (d: string) => void; model: ModelInfo | undefined }) {
  return (
    <>
      <div className="sidebar-head">
        <span className="count">
          Every tile of a disaster, ranked by severely damaged roof. {model ? `Model: ${model.label}.` : ""}
        </span>
      </div>
      <ul className="scene-list" role="listbox">
        {events.map((e) => (
          <li key={e.disaster} role="option" aria-selected={e.disaster === selected} onClick={() => onSelect(e.disaster)}>
            <div className="scene-title">
              <strong>{titleCase(e.disaster)}</strong>
              <span className="subtle">{e.assessed}/{e.tiles}</span>
            </div>
            <span className="scene-id">{titleCase(e.disaster_type)} · {e.alerts} {e.alerts === 1 ? "alert" : "alerts"}</span>
          </li>
        ))}
      </ul>
    </>
  );
}

function Fit({ points, id }: { points: L.LatLng[]; id: string }) {
  const map = useMap();
  // refit when another event's tiles arrive, not when the same tiles are refreshed during a running job
  useEffect(() => { if (points.length) map.fitBounds(L.latLngBounds(points), { padding: [40, 40], maxZoom: 15 }); }, [map, id, points.length > 0]);
  return null;
}

export default function EventView({ disaster, modelId, onTile, onChanged }: {
  disaster: string | null; modelId: string | null; onTile: (pairId: string) => void; onChanged: () => void;
}) {
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [job, setJob] = useState<EventJob>({ state: "idle" });
  const [error, setError] = useState<string | null>(null);

  const load = () => {
    if (!disaster || !modelId) return Promise.resolve();
    return api.event(disaster, modelId).then((d) => { setDetail(d); setJob(d.job); setError(null); }).catch((e) => setError(String(e)));
  };
  useEffect(() => { setDetail(null); void load(); }, [disaster, modelId]);

  // While tiles are being assessed, refresh every 4 s.
  useEffect(() => {
    if (job.state !== "running") return;
    const t = setTimeout(() => { void load().then(onChanged); }, 4000);
    return () => clearTimeout(t);
  }, [job, detail]);

  const start = (n: number) => {
    if (!disaster || !modelId) return;
    api.assessEvent(disaster, modelId, n).then(setJob).catch((e) => setError(String(e)));
  };

  const missing = detail ? detail.tiles.filter((t) => !t.assessed).length : 0;
  const points = detail ? detail.frames.flatMap((f) => ll(f.ring)) : [];
  const done = detail ? detail.tiles.filter((t) => t.assessed) : [];
  const totals = detail ? detail.tiles.reduce((a, t) => ({ high: a.high + (t.high ?? 0), medium: a.medium + (t.medium ?? 0), m2: a.m2 + (t.severe_m2 ?? 0) }), { high: 0, medium: 0, m2: 0 }) : null;

  return (
    <>
      <main className="map">
        <MapContainer center={[0, 0]} zoom={2} maxZoom={20} zoomSnap={0.5} preferCanvas style={{ height: "100%" }}>
          <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={20}
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
          {detail?.frames.map((f) => (
            <Polygon key={f.pair_id} positions={ll(f.ring)}
              pathOptions={f.assessed ? { color: "#1C1B19", weight: 1, dashArray: "2 4", fill: false } : { color: "#8F8C84", weight: 1, dashArray: "2 4", fillColor: "#8F8C84", fillOpacity: 0.1 }}
              eventHandlers={{ click: () => onTile(f.pair_id) }}>
              <Tooltip sticky>Tile {f.pair_id.split("_").pop()}{f.assessed ? "" : ": not assessed yet (click to assess)"}</Tooltip>
            </Polygon>
          ))}
          {detail?.alerts.map((a) => {
            const c = a.severity === "high" ? CLASS_COLOUR.destroyed : CLASS_COLOUR["major-damage"];
            return (
              <Polygon key={a.alert_id} positions={ll(a.ring)} pathOptions={{ color: c, weight: 2, fillColor: c, fillOpacity: 0.3 }}
                eventHandlers={{ click: () => onTile(a.pair_id) }}>
                <Tooltip sticky>{a.severity === "high" ? "High" : "Medium"} alert · {area(a.severe_m2)} severe roof · tile {a.pair_id.split("_").pop()}</Tooltip>
              </Polygon>
            );
          })}
          <Fit points={points} id={disaster ?? ""} />
        </MapContainer>
        {(!disaster || error) && <div className={`map-status ${error ? "error" : ""}`}><div>{error ?? "Select an event"}</div></div>}
        <div className="legend panel-float">
          <span><i className="swatch" style={{ background: CLASS_COLOUR.destroyed }} />High alert</span>
          <span><i className="swatch" style={{ background: CLASS_COLOUR["major-damage"] }} />Medium alert</span>
          <span><i className="swatch dashed" />Tile</span>
        </div>
      </main>
      <aside className="detail">
        <section>
          <h1>{disaster ? titleCase(disaster) : "Event"}</h1>
          {detail && totals && (
            <p className="meta">{detail.tiles.length} tiles · {detail.tiles.length - missing} assessed · {totals.high} high, {totals.medium} medium alerts · {area(totals.m2)} severe roof</p>
          )}
          {missing > 0 && (
            <div className="actions">
              {job.state === "running" ? (
                <span className="status-running">Assessing tile {(job.done ?? 0) + 1} of {job.total}…</span>
              ) : (
                <>
                  <button className="button primary" onClick={() => start(10)}>Assess {Math.min(10, missing)} more</button>
                  {missing > 10 && <button className="button" onClick={() => start(25)} title="About a minute per tile on this server">Assess {Math.min(25, missing)}</button>}
                </>
              )}
            </div>
          )}
          {job.state === "running" && job.total ? <div className="progress"><span style={{ width: `${((job.done ?? 0) / job.total) * 100}%` }} /></div> : null}
          {job.state === "failed" && <p className="meta error-text">{job.error}</p>}
        </section>
        <section>
          <h2>Tiles by severely damaged roof</h2>
          {detail && done.length === 0 ? <p className="empty-note">No tile of this event has been assessed yet. The server assesses about one tile a minute; assessed tiles are kept.</p> : detail ? (
            <table>
              <thead><tr><th>#</th><th>Tile</th><th className="num">Alerts</th><th className="num">Severe roof</th><th className="num" title="Severely damaged buildings in the xBD labels (scoring only)">xBD</th></tr></thead>
              <tbody>
                {done.map((t: EventTile) => (
                  <tr key={t.pair_id} className="clickable" onClick={() => onTile(t.pair_id)}>
                    <td>{t.rank ?? "–"}</td>
                    <td className="mono">{t.tile}</td>
                    <td className="num">{t.assessed ? <>{t.high ? <span className="sev sev-high">{t.high}</span> : 0}{t.medium ? <> + <span className="sev sev-medium">{t.medium}</span></> : null}</> : <span className="subtle">–</span>}</td>
                    <td className="num">{t.assessed ? area(t.severe_m2 ?? 0) : <span className="subtle">–</span>}</td>
                    <td className="num subtle">{t.xbd_severe}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : <p className="empty-note">{error ?? "Loading…"}</p>}
          <p className="rank-note">
            {missing > 0 && <>{missing} of {detail?.tiles.length} tiles are not assessed yet (grey on the map). </>}
            Alerts: high + medium. The xBD column counts severely damaged buildings in the labels, for scoring only.
            {detail?.rank_agreement_with_xbd != null && <> Rank agreement between model and labels: ρ = {detail.rank_agreement_with_xbd.toFixed(2)}.</>}
          </p>
        </section>
      </aside>
    </>
  );
}
