import { useEffect } from "react";
import L from "leaflet";
import { CircleMarker, ImageOverlay, MapContainer, TileLayer, Tooltip, useMap } from "react-leaflet";
import { api, Assessment, CLASS_COLOUR, Feature, NOT_DETECTED_COLOUR, Scene, tileNo, titleCase } from "../api";
import type { Focus, Mode } from "../App";
import type { MapOptions } from "./DamageMap";

// Geographic view: OpenStreetMap basemap; the tile, its damage and its alerts placed with the image's own
// georeferencing (GDAL geotransform, EPSG:4326). Zoomed out, every tile shows as a dot at its location.

type GT = number[];
const toLatLng = (gt: GT, x: number, y: number) => L.latLng(gt[3] + x * gt[4] + y * gt[5], gt[0] + x * gt[1] + y * gt[2]);
const tileBounds = (gt: GT, size: number) => L.latLngBounds(toLatLng(gt, 0, 0), toLatLng(gt, size, size));

interface Props {
  assessment: Assessment; gt: GT; options: MapOptions; selected: string | null; onSelect: (id: string) => void;
  focus: Focus; mode: Mode; scenes: Scene[]; onScene: (id: string) => void;
}

function Features({ assessment, gt, options, selected, onSelect }: Pick<Props, "assessment" | "gt" | "options" | "selected" | "onSelect">) {
  const map = useMap();
  useEffect(() => {
    if (!options.damage) return;
    const layer = L.geoJSON(assessment.features as unknown as GeoJSON.Feature[], {
      coordsToLatLng: (c) => toLatLng(gt, c[0], c[1]),
      style: (f) => {
        const feat = f as unknown as Feature;
        const fill = feat.properties.predicted_class ? CLASS_COLOUR[feat.properties.predicted_class] : NOT_DETECTED_COLOUR;
        return { color: feat.id === selected ? "#FFFFFF" : fill, weight: feat.id === selected ? 3 : 1, fillColor: fill, fillOpacity: 0.5 };
      },
      onEachFeature: (f, l) => { l.on("click", () => onSelect((f as unknown as Feature).id)); },
    }).addTo(map);
    return () => { layer.remove(); };
  }, [map, assessment, gt, options.damage, selected, onSelect]);
  return null;
}

function Areas({ assessment, gt, mode }: { assessment: Assessment; gt: GT; mode: Mode }) {
  const map = useMap();
  useEffect(() => {
    const areas = mode === "area" ? (assessment.alerts ?? []) : assessment.zones.slice(0, 5);
    const group = L.layerGroup(areas.map((z, i) =>
      L.polygon(z.hull_px.map(([x, y]) => toLatLng(gt, x, y)), { color: "#1C1B19", weight: 1.5, dashArray: "5 4", fill: false, interactive: false })
        .bindTooltip(String(i + 1), { permanent: true, direction: "center", className: "zone-label" }),
    )).addTo(map);
    return () => { group.remove(); };
  }, [map, assessment, gt, mode]);
  return null;
}

function Controller({ gt, size, focus, pairId }: { gt: GT; size: number; focus: Focus; pairId: string }) {
  const map = useMap();
  useEffect(() => { map.fitBounds(tileBounds(gt, size), { padding: [24, 24] }); }, [map, pairId]);
  useEffect(() => { if (focus) map.flyTo(toLatLng(gt, focus.x, focus.y), 18, { duration: 0.5 }); }, [map, focus, gt]);
  return null;
}

export default function GeoMap({ assessment, gt, options, selected, onSelect, focus, mode, scenes, onScene }: Props) {
  const size = assessment.scene.size_px ?? 1024;
  const bounds = tileBounds(gt, size);
  return (
    <MapContainer bounds={bounds} maxZoom={20} zoomSnap={0.5} preferCanvas style={{ height: "100%" }}>
      <TileLayer url="https://tile.openstreetmap.org/{z}/{x}/{y}.png" maxNativeZoom={19} maxZoom={20}
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' />
      <ImageOverlay key={assessment.pair_id + options.phase} url={api.imageUrl(assessment.pair_id, options.phase)} bounds={bounds} opacity={0.95} />
      {options.pixelMap && assessment.has_damage_map && <ImageOverlay url={api.damageMapUrl(assessment.id)} bounds={bounds} opacity={0.8} />}
      <Features assessment={assessment} gt={gt} options={options} selected={selected} onSelect={onSelect} />
      {options.zones && <Areas assessment={assessment} gt={gt} mode={mode} />}
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
      <Controller gt={gt} size={size} focus={focus} pairId={assessment.pair_id} />
    </MapContainer>
  );
}
