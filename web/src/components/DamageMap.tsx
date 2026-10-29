import { useEffect, useMemo } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, useMap } from "react-leaflet";
import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, Feature, NOT_DETECTED_COLOUR } from "../api";
import type { Focus } from "../App";

export interface MapOptions { phase: "pre" | "post"; showTruth: boolean; errorsOnly: boolean; showZones: boolean; damageMap: boolean }

const SIZE = 1024;
const BOUNDS: L.LatLngBoundsExpression = [[0, 0], [SIZE, SIZE]];
// Image pixels (x right, y down) -> Leaflet CRS.Simple coordinates (lat up).
const toLatLng = (x: number, y: number) => L.latLng(SIZE - y, x);

interface Props {
  assessment: Assessment | null; loading: boolean; error: string | null;
  options: MapOptions; onOptions: (o: MapOptions) => void;
  selected: string | null; onSelect: (id: string | null) => void; focus: Focus;
}

function Buildings({ features, options, selected, onSelect }: { features: Feature[]; options: MapOptions; selected: string | null; onSelect: (id: string) => void }) {
  const map = useMap();
  useEffect(() => {
    const shown = options.errorsOnly
      ? features.filter((f) => f.properties.true_class && f.properties.predicted_class !== f.properties.true_class)
      : features;
    const layer = L.geoJSON(shown as unknown as GeoJSON.FeatureCollection["features"], {
      coordsToLatLng: (c) => toLatLng(c[0], c[1]),
      style: (f) => {
        const p = (f as unknown as Feature).properties;
        const fill = p.predicted_class ? CLASS_COLOUR[p.predicted_class] : NOT_DETECTED_COLOUR;
        const edge = options.showTruth ? (p.true_class ? CLASS_COLOUR[p.true_class] : "#FFFFFF") : fill;
        const isSel = (f as unknown as Feature).id === selected;
        return {
          color: isSel ? "#38BDF8" : edge, weight: isSel ? 3.5 : options.showTruth ? 2.2 : 1.3,
          fillColor: fill, fillOpacity: options.damageMap ? 0.05 : 0.38,
          dashArray: p.review_status === "needs_review" ? "4 3" : undefined,
        };
      },
      onEachFeature: (f, l) => {
        const p = (f as unknown as Feature).properties;
        l.on("click", () => onSelect((f as unknown as Feature).id));
        l.bindTooltip(
          `${p.predicted_class ? CLASS_LABEL[p.predicted_class] : "Not detected"} · ${(p.confidence * 100).toFixed(0)}%` +
          (p.true_class ? `<br/><span style="opacity:.7">xBD: ${CLASS_LABEL[p.true_class]}</span>` : ""),
          { sticky: true },
        );
      },
    }).addTo(map);
    return () => { layer.remove(); };
  }, [map, features, options, selected, onSelect]);
  return null;
}

function Zones({ assessment }: { assessment: Assessment }) {
  const map = useMap();
  useEffect(() => {
    const group = L.layerGroup(assessment.zones.map((z) =>
      L.polygon(z.hull_px.map(([x, y]) => toLatLng(x, y)), { color: "#38BDF8", weight: 2, dashArray: "6 4", fill: false, interactive: false })
        .bindTooltip(`${z.zone_id} · priority ${z.priority}`, { permanent: true, className: "zt", direction: "top" }),
    )).addTo(map);
    return () => { group.remove(); };
  }, [map, assessment]);
  return null;
}

function Controller({ focus, pairId }: { focus: Focus; pairId?: string }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(BOUNDS); }, [map, pairId]);
  useEffect(() => { if (focus) map.flyTo(toLatLng(focus.x, focus.y), focus.zoom, { duration: 0.6 }); }, [map, focus]);
  return null;
}

export default function DamageMap({ assessment, loading, error, options, onOptions, selected, onSelect, focus }: Props) {
  const set = (patch: Partial<MapOptions>) => onOptions({ ...options, ...patch });
  const features = useMemo(() => assessment?.features ?? [], [assessment]);
  return (
    <div className="mapwrap">
      <MapContainer crs={L.CRS.Simple} bounds={BOUNDS} minZoom={-2} maxZoom={4} zoomSnap={0.25} preferCanvas attributionControl={false}
        style={{ height: "100%" }}>
        {assessment && (
          <>
            <ImageOverlay key={assessment.pair_id + options.phase} url={api.imageUrl(assessment.pair_id, options.phase)} bounds={BOUNDS} />
            {options.damageMap && assessment.has_damage_map && (
              <ImageOverlay key={"dm" + assessment.id} url={api.damageMapUrl(assessment.id)} bounds={BOUNDS} opacity={0.85} />
            )}
            <Buildings features={features} options={options} selected={selected} onSelect={onSelect} />
            {options.showZones && <Zones assessment={assessment} />}
          </>
        )}
        <Controller focus={focus} pairId={assessment?.pair_id} />
      </MapContainer>

      {assessment && (
        <div className="float ctl">
          <div className="seg">
            <button className={`btn ${options.phase === "pre" ? "on" : ""}`} onClick={() => set({ phase: "pre" })}>Before</button>
            <button className={`btn ${options.phase === "post" ? "on" : ""}`} onClick={() => set({ phase: "post" })}>After</button>
          </div>
          <div className="seg">
            <button className={`btn ${options.showTruth ? "on" : ""}`} onClick={() => set({ showTruth: !options.showTruth })}>xBD truth</button>
            <button className={`btn ${options.errorsOnly ? "on" : ""}`} onClick={() => set({ errorsOnly: !options.errorsOnly })}>Errors only</button>
          </div>
          <div className="seg">
            <button className={`btn ${options.showZones ? "on" : ""}`} onClick={() => set({ showZones: !options.showZones })}>Zones</button>
            {assessment.has_damage_map && (
              <button className={`btn ${options.damageMap ? "on" : ""}`} onClick={() => set({ damageMap: !options.damageMap })}>Pixel map</button>
            )}
          </div>
        </div>
      )}

      <div className="float leg">
        {CLASSES.map((c) => (
          <div className="row" key={c}><span className="sw" style={{ background: CLASS_COLOUR[c] + "66", border: `1.5px solid ${CLASS_COLOUR[c]}` }} />{CLASS_LABEL[c]}</div>
        ))}
        <div className="row"><span className="sw" style={{ border: "1.5px dashed #E2E8F0" }} />Needs review</div>
        {options.showTruth && <div className="row dim">Fill = model · outline = xBD truth</div>}
      </div>

      {(loading || error || !assessment) && (
        <div className="empty">
          {loading ? <div style={{ textAlign: "center" }}><div className="spinner" />Assessing scene…</div>
            : error ? <div className="err">{error}</div> : "Select a scene"}
        </div>
      )}
    </div>
  );
}
