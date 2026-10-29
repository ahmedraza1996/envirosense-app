import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import { ImageOverlay, MapContainer, useMap } from "react-leaflet";
import { api, Assessment, CLASS_COLOUR, CLASS_LABEL, CLASSES, Feature, NOT_DETECTED_COLOUR } from "../api";
import type { Focus, Mode } from "../App";
import type { Scene } from "../api";
import GeoMap from "./GeoMap";

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
  selected: string | null; onSelect: (id: string | null) => void; focus: Focus; mode: Mode;
  scenes: Scene[]; onScene: (id: string) => void;
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

function Areas({ assessment, mode }: { assessment: Assessment; mode: Mode }) {
  const map = useMap();
  useEffect(() => {
    // Area mode: every alert area, numbered as in the alert list. Building mode: the top priority areas.
    const areas = mode === "area" ? (assessment.alerts ?? []) : assessment.zones.slice(0, LABELLED_ZONES);
    const group = L.layerGroup(areas.map((z, i) =>
      L.polygon(z.hull_px.map(([x, y]) => toLatLng(x, y)),
        { color: "#1C1B19", weight: 1.5, dashArray: "5 4", fill: false, interactive: false })
        .bindTooltip(String(i + 1), { permanent: true, direction: "center", className: "zone-label" }),
    )).addTo(map);
    return () => { group.remove(); };
  }, [map, assessment, mode]);
  return null;
}

function Controller({ focus, pairId }: { focus: Focus; pairId?: string }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(BOUNDS, { padding: [24, 24] }); }, [map, pairId]);
  useEffect(() => { if (focus) map.flyTo(toLatLng(focus.x, focus.y), focus.zoom, { duration: 0.5 }); }, [map, focus]);
  return null;
}

function LayersMenu({ options, set, hasPixelMap, mode }: { options: MapOptions; set: (p: Partial<MapOptions>) => void; hasPixelMap: boolean; mode: Mode }) {
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
          {item("damage", mode === "area" ? "Detected structures" : "Predicted damage")}
          {mode === "building" && item("compare", "Compare with xBD labels")}
          {mode === "building" && item("mismatches", "Show disagreements only")}
          {item("zones", mode === "area" ? "Alert areas" : "Priority areas")}
          {item("pixelMap", "Pixel damage map", !hasPixelMap)}
        </div>
      )}
    </div>
  );
}

export default function DamageMap({ assessment, loading, error, options, onOptions, selected, onSelect, focus, mode, scenes, onScene }: Props) {
  const set = (patch: Partial<MapOptions>) => onOptions({ ...options, ...patch });
  const features = useMemo(() => assessment?.features ?? [], [assessment]);
  const [view, setView] = useState<"image" | "geo">("image");
  const gt = assessment?.scene.geotransform;
  return (
    <main className="map">
      {view === "geo" && assessment && gt ? (
        <GeoMap assessment={assessment} gt={gt} options={options} selected={selected} onSelect={onSelect}
          focus={focus} mode={mode} scenes={scenes} onScene={onScene} />
      ) : (
      <MapContainer crs={L.CRS.Simple} bounds={BOUNDS} minZoom={-2} maxZoom={4} zoomSnap={0.25} preferCanvas attributionControl={false}
        style={{ height: "100%" }}>
        {assessment && (
          <>
            <ImageOverlay key={assessment.pair_id + options.phase} url={api.imageUrl(assessment.pair_id, options.phase)} bounds={BOUNDS} />
            {options.pixelMap && assessment.has_damage_map && (
              <ImageOverlay key={"pm" + assessment.id} url={api.damageMapUrl(assessment.id)} bounds={BOUNDS} opacity={0.8} />
            )}
            <Buildings features={features} options={options} selected={selected} onSelect={onSelect} />
            {options.zones && <Areas assessment={assessment} mode={mode} />}
          </>
        )}
        <Controller focus={focus} pairId={assessment?.pair_id} />
      </MapContainer>
      )}

      {assessment && (
        <div className="map-toolbar">
          <div className="toolbar-group">
            <div className="segmented panel-float" role="group" aria-label="View">
              <button aria-pressed={view === "image"} onClick={() => setView("image")}>Image</button>
              <button aria-pressed={view === "geo"} onClick={() => setView("geo")} disabled={!gt}>Map</button>
            </div>
            <div className="segmented panel-float" role="group" aria-label="Imagery">
              <button aria-pressed={options.phase === "pre"} onClick={() => set({ phase: "pre" })}>Before</button>
              <button aria-pressed={options.phase === "post"} onClick={() => set({ phase: "post" })}>After</button>
            </div>
          </div>
          <LayersMenu options={options} set={set} hasPixelMap={assessment.has_damage_map} mode={mode} />
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
          <div>{error ? error : loading ? (mode === "area" ? "Detecting damage…" : "Assessing tile…") : "Select a tile"}</div>
        </div>
      )}
    </main>
  );
}
