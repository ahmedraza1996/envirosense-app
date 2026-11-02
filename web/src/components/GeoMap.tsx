import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, ImageOverlay, MapContainer, Polygon, TileLayer, Tooltip, useMap } from "react-leaflet";
import { api, Assessment, Context, CLASS_COLOUR, CLASS_LABEL, Feature, FOOTPRINT_COLOUR, NOT_DETECTED_COLOUR, Reviews, Scene, tileNo, titleCase } from "../api";
import type { Focus, Mode } from "../App";
import type { MapOptions } from "./DamageMap";

// Geographic view: OpenStreetMap basemap; the tile, its damage and its alerts placed with the image's own
// georeferencing (GDAL geotransform, EPSG:4326). Zoomed out, every tile shows as a dot at its location.

type GT = number[];
const toLatLng = (gt: GT, x: number, y: number) => L.latLng(gt[3] + x * gt[4] + y * gt[5], gt[0] + x * gt[1] + y * gt[2]);
const corners = (gt: GT, w: number, h: number) => [toLatLng(gt, 0, 0), toLatLng(gt, w, 0), toLatLng(gt, w, h), toLatLng(gt, 0, h)];
const tileBounds = (gt: GT, w: number, h: number) => L.latLngBounds(corners(gt, w, h));

interface Props {
  assessment: Assessment; gt: GT; options: MapOptions; selected: string | null; onSelect: (id: string) => void;
  focus: Focus; mode: Mode; scenes: Scene[]; onScene: (id: string) => void;
  reviews: Reviews | null; alertId: string | null; context: Context | null;
}

function Features({ assessment, gt, options, selected, onSelect }: Pick<Props, "assessment" | "gt" | "options" | "selected" | "onSelect">) {
  const map = useMap();
  useEffect(() => {
    if (!options.damage) return;
    const layer = L.geoJSON(assessment.features as unknown as GeoJSON.Feature[], {
      coordsToLatLng: (c) => toLatLng(gt, c[0], c[1]),
      style: (f) => {
        const feat = f as unknown as Feature;
        const sel = feat.id === selected;
        if (options.phase === "pre") return { color: sel ? "#FFFFFF" : FOOTPRINT_COLOUR, weight: sel ? 3 : 1.5, fillColor: FOOTPRINT_COLOUR, fillOpacity: 0.15 };
        const fill = feat.properties.predicted_class ? CLASS_COLOUR[feat.properties.predicted_class] : NOT_DETECTED_COLOUR;
        return { color: sel ? "#FFFFFF" : fill, weight: sel ? 3 : 1, fillColor: fill, fillOpacity: 0.6 };
      },
      onEachFeature: (f, l) => {
        const p = (f as unknown as Feature).properties;
        l.on("click", () => onSelect((f as unknown as Feature).id));
        l.bindTooltip(options.phase === "pre" ? "Building found by the model"
          : `${p.predicted_class ? CLASS_LABEL[p.predicted_class] : "Not detected"} (${Math.round(p.confidence * 100)}%)`, { sticky: true, direction: "top" });
      },
    }).addTo(map);
    return () => { layer.remove(); };
  }, [map, assessment, gt, options.damage, options.phase, selected, onSelect]);
  return null;
}

function Areas({ assessment, gt, mode, reviews, alertId }: { assessment: Assessment; gt: GT; mode: Mode; reviews: Reviews | null; alertId: string | null }) {
  const map = useMap();
  useEffect(() => {
    const all = mode === "area" ? (assessment.alerts ?? []) : assessment.zones.slice(0, 5);
    // Alert areas are filled by severity so the affected neighbourhoods stand out on the street map; confirmed alerts have a solid
    // outline, dismissed ones are left out, the selected one is outlined heavily.
    const group = L.layerGroup(all.map((z, i) => {
      const id = "alert_id" in z ? (z as { alert_id: string }).alert_id : null;
      const status = id ? reviews?.alerts[id]?.status ?? "pending" : "pending";
      if (status === "dismissed" || status === "retracted") return null;
      const sev = "severity" in z ? (z as { severity: string }).severity : null;
      const c = sev === "high" ? CLASS_COLOUR.destroyed : sev === "medium" ? CLASS_COLOUR["major-damage"] : "#1C1B19";
      const sel = id !== null && id === alertId;
      return L.polygon(z.hull_px.map(([x, y]) => toLatLng(gt, x, y)),
        { color: sel ? "#1C1B19" : c, weight: sel ? 4 : status === "confirmed" ? 3 : 2, dashArray: status === "confirmed" ? undefined : "6 4",
          fill: !!sev, fillColor: c, fillOpacity: sel ? 0.22 : 0.12, interactive: false })
        .bindTooltip(String(i + 1), { permanent: true, direction: "center", className: "zone-label" });
    }).filter((x): x is L.Polygon => x !== null)).addTo(map);
    return () => { group.remove(); };
  }, [map, assessment, gt, mode, reviews, alertId]);
  return null;
}

const FACILITY_LETTER: Record<string, string> = { Hospital: "H", Clinic: "C", School: "S", "Fire station": "F", "Police station": "P" };

function Facilities({ context }: { context: Context }) {
  const map = useMap();
  useEffect(() => {
    const group = L.layerGroup(context.facilities.map((f) =>
      L.marker([f.lat, f.lon], {
        icon: L.divIcon({ className: "facility", html: `<span>${FACILITY_LETTER[f.kind] ?? "·"}</span>`, iconSize: [18, 18] }),
        keyboard: false,
      }).bindTooltip(`${f.kind}${f.name ? `: ${f.name}` : ""}`, { direction: "top" }))).addTo(map);
    return () => { group.remove(); };
  }, [map, context]);
  return null;
}

function Controller({ bounds, gt, focus, pairId }: { bounds: L.LatLngBounds; gt: GT; focus: Focus; pairId: string }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(bounds, { padding: [24, 24] }); }, [map, pairId]);
  useEffect(() => { if (focus) map.flyTo(toLatLng(gt, focus.x, focus.y), 18, { duration: 0.5 }); }, [map, focus, gt]);
  return null;
}

export default function GeoMap({ assessment, gt, options, selected, onSelect, focus, mode, scenes, onScene, reviews, alertId, context }: Props) {
  const w = assessment.scene.width_px ?? assessment.scene.size_px ?? 1024;
  const h = assessment.scene.height_px ?? assessment.scene.size_px ?? 1024;
  const bounds = tileBounds(gt, w, h);
  // Images whose grid is rotated against north are drawn from a north-up copy (backend), so image and outlines agree.
  const rotated = assessment.scene.geo_bounds ?? null;
  const overlayBounds = rotated ? L.latLngBounds(rotated) : bounds;
  const satUrl = rotated ? api.geoUrl(assessment.id, options.phase) : api.imageUrl(assessment.pair_id, options.phase);
  const damageUrl = rotated ? api.geoUrl(assessment.id, "damage") : api.damageMapUrl(assessment.id);
  return (
    <MapContainer bounds={bounds} maxZoom={20} zoomSnap={0.5} preferCanvas style={{ height: "100%" }}>
      <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={20}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
      <Polygon positions={corners(gt, w, h)} pathOptions={{ color: "#1C1B19", weight: 1, dashArray: "2 4", fill: false, interactive: false }} />
      {options.satellite && <ImageOverlay key={assessment.pair_id + options.phase} url={satUrl} bounds={overlayBounds} opacity={options.satelliteOpacity} />}
      {options.pixelMap && options.phase === "post" && assessment.has_damage_map && <ImageOverlay key={"dm" + assessment.id} url={damageUrl} bounds={overlayBounds} opacity={0.8} />}
      <Features assessment={assessment} gt={gt} options={options} selected={selected} onSelect={onSelect} />
      {options.zones && options.phase === "post" && <Areas assessment={assessment} gt={gt} mode={mode} reviews={reviews} alertId={alertId} />}
      {options.facilities && context?.available && <Facilities context={context} />}
      {scenes.filter((s) => s.centre_lat != null && s.pair_id !== assessment.pair_id).map((s) => {
        const share = s.buildings ? s.severe_true / s.buildings : 0;
        const colour = share >= 0.5 ? CLASS_COLOUR.destroyed : share >= 0.15 ? CLASS_COLOUR["major-damage"] : CLASS_COLOUR["no-damage"];
        return (
          <CircleMarker key={s.pair_id} center={[s.centre_lat!, s.centre_lon!]} radius={4 + Math.min(6, s.severe_true / 40)}
            pathOptions={{ color: "#FFFFFF", weight: 1, fillColor: colour, fillOpacity: 0.9 }} eventHandlers={{ click: () => onScene(s.pair_id) }}>
            <Tooltip direction="top">{titleCase(s.disaster)}, tile {tileNo(s.pair_id)} · {s.severe_true} of {s.buildings} severe (xBD)</Tooltip>
          </CircleMarker>
        );
      })}
      <Controller bounds={bounds} gt={gt} focus={focus} pairId={assessment.pair_id} />
    </MapContainer>
  );
}
