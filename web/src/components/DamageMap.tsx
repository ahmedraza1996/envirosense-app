import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, useMap } from "react-leaflet";
import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, Feature, NOT_DETECTED_COLOUR } from "../api";
import type { Focus } from "../App";

export interface MapOptions {
  phase: "pre" | "post"; damage: boolean; compare: boolean; mismatches: boolean; zones: boolean; pixelMap: boolean;
}

const SIZE = 1024;
const BOUNDS: L.LatLngBoundsExpression = [[0, 0], [SIZE, SIZE]];
const LABELLED_ZONES = 5;
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
    const shown = options.mismatches
      ? features.filter((f) => f.properties.true_class && f.properties.predicted_class !== f.properties.true_class)
      : features;
    const layer = L.geoJSON(shown as unknown as GeoJSON.Feature[], {
      coordsToLatLng: (c) => toLatLng(c[0], c[1]),
      style: (f) => {
        const feat = f as unknown as Feature;
        const p = feat.properties;
        const fill = p.predicted_class ? CLASS_COLOUR[p.predicted_class] : NOT_DETECTED_COLOUR;
        const edge = options.compare ? (p.true_class ? CLASS_COLOUR[p.true_class] : "#FFFFFF") : fill;
        const isSel = feat.id === selected;
        return {
          color: isSel ? "#FFFFFF" : edge, weight: isSel ? 3 : options.compare ? 2 : 1,
          fillColor: fill, fillOpacity: options.damage ? 0.45 : 0, opacity: options.damage || options.compare || isSel ? 1 : 0,
          dashArray: p.review_status === "needs_review" ? "3 3" : undefined,
        };
      },
      onEachFeature: (f, l) => {
        const p = (f as unknown as Feature).properties;
        l.on("click", () => onSelect((f as unknown as Feature).id));
        l.bindTooltip(
          `${p.predicted_class ? CLASS_LABEL[p.predicted_class] : "Not detected"} (${Math.round(p.confidence * 100)}%)` +
          (p.true_class ? ` · xBD ${CLASS_LABEL[p.true_class]}` : ""), { sticky: true, direction: "top" },
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
    // Only the highest-priority areas are drawn; their numbers match the "Priority areas" table.
    const group = L.layerGroup(assessment.zones.slice(0, LABELLED_ZONES).map((z, i) =>
      L.polygon(z.hull_px.map(([x, y]) => toLatLng(x, y)),
        { color: "#1C1B19", weight: 1.5, dashArray: "5 4", fill: false, interactive: false })
        .bindTooltip(String(i + 1), { permanent: true, direction: "center", className: "zone-label" }),
    )).addTo(map);
    return () => { group.remove(); };
  }, [map, assessment]);
  return null;
}

function Controller({ focus, pairId }: { focus: Focus; pairId?: string }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(BOUNDS, { padding: [24, 24] }); }, [map, pairId]);
  useEffect(() => { if (focus) map.flyTo(toLatLng(focus.x, focus.y), focus.zoom, { duration: 0.5 }); }, [map, focus]);
  return null;
}

function LayersMenu({ options, set, hasPixelMap }: { options: MapOptions; set: (p: Partial<MapOptions>) => void; hasPixelMap: boolean }) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);
  const item = (key: keyof MapOptions, label: string, disabled = false) => (
    <label className={disabled ? "disabled" : ""}>
      <input type="checkbox" checked={Boolean(options[key])} disabled={disabled} onChange={(e) => set({ [key]: e.target.checked })} />
      {label}
    </label>
  );
  return (
    <div className="layers" ref={ref}>
      <button className="button panel-float" aria-expanded={open} onClick={() => setOpen(!open)}>Layers</button>
      {open && (
        <div className="layers-menu panel-float">
          {item("damage", "Predicted damage")}
          {item("compare", "Compare with xBD labels")}
          {item("mismatches", "Show disagreements only")}
          {item("zones", "Priority areas")}
          {item("pixelMap", "Pixel damage map", !hasPixelMap)}
        </div>
      )}
    </div>
  );
}

export default function DamageMap({ assessment, loading, error, options, onOptions, selected, onSelect, focus }: Props) {
  const set = (patch: Partial<MapOptions>) => onOptions({ ...options, ...patch });
  const features = useMemo(() => assessment?.features ?? [], [assessment]);
  return (
    <main className="map">
      <MapContainer crs={L.CRS.Simple} bounds={BOUNDS} minZoom={-2} maxZoom={4} zoomSnap={0.25} preferCanvas attributionControl={false}
        style={{ height: "100%" }}>
        {assessment && (
          <>
            <ImageOverlay key={assessment.pair_id + options.phase} url={api.imageUrl(assessment.pair_id, options.phase)} bounds={BOUNDS} />
            {options.pixelMap && assessment.has_damage_map && (
              <ImageOverlay key={"pm" + assessment.id} url={api.damageMapUrl(assessment.id)} bounds={BOUNDS} opacity={0.8} />
            )}
            <Buildings features={features} options={options} selected={selected} onSelect={onSelect} />
            {options.zones && <Zones assessment={assessment} />}
          </>
        )}
        <Controller focus={focus} pairId={assessment?.pair_id} />
      </MapContainer>

      {assessment && (
        <div className="map-toolbar">
          <div className="segmented panel-float" role="group" aria-label="Imagery">
            <button aria-pressed={options.phase === "pre"} onClick={() => set({ phase: "pre" })}>Before</button>
            <button aria-pressed={options.phase === "post"} onClick={() => set({ phase: "post" })}>After</button>
          </div>
          <LayersMenu options={options} set={set} hasPixelMap={assessment.has_damage_map} />
        </div>
      )}

      {assessment && (
        <div className="legend panel-float">
          {CLASSES.map((c) => <span key={c}><i className="swatch" style={{ background: CLASS_COLOUR[c] }} />{CLASS_LABEL[c]}</span>)}
          <span><i className="swatch dashed" />Needs review</span>
          {options.compare && <span className="subtle">Fill: model · outline: xBD</span>}
        </div>
      )}

      {(loading || error || !assessment) && (
        <div className={`map-status ${error ? "error" : ""}`}>
          <div>{error ? error : loading ? "Assessing tile…" : "Select a tile"}</div>
        </div>
      )}
    </main>
  );
}
