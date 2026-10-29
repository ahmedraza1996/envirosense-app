// Typed client for the FastAPI backend (app/api/main.py).

export type DamageClass = "no-damage" | "minor-damage" | "major-damage" | "destroyed";
export const CLASSES: DamageClass[] = ["no-damage", "minor-damage", "major-damage", "destroyed"];
export const CLASS_LABEL: Record<DamageClass, string> = {
  "no-damage": "No damage", "minor-damage": "Minor", "major-damage": "Major", destroyed: "Destroyed",
};
// Ordinal damage ramp; the only saturated colours in the UI (kept in sync with styles.css).
export const CLASS_COLOUR: Record<DamageClass, string> = {
  "no-damage": "#3F8F5F", "minor-damage": "#D9A520", "major-damage": "#D9622B", destroyed: "#B3261E",
};
export const NOT_DETECTED_COLOUR = "#8F8C84";

export interface ModelInfo { id: string; label: string; kind: "classifier" | "unet"; run: string }

export interface Scene {
  pair_id: string; split: string; disaster: string; disaster_type: string; buildings: number;
  true_none: number; true_minor: number; true_major: number; true_destroyed: number; true_unclassified: number;
  severe_true: number; pre_date?: string; post_date?: string;
  centre_lat?: number; centre_lon?: number; pixel_size_m?: number; geotransform?: number[]; size_px?: number;
  // uploads only
  source?: "upload"; name?: string; width_px?: number; height_px?: number; event_date?: string | null;
  before?: BeforeInfo; notes?: string[];
}

export interface BeforeInfo {
  kind: "archive" | "upload"; archive?: string; file?: string;
  tiles?: { tile: string; capture_date: string; covers: number }[];
  coverage: number; shift_px: [number, number] | null; shift_m: number | null; response: number | null; corrected: boolean;
}

export interface Upload {
  id: string; name: string; disaster_type: string; event_date: string | null; model_id: string; created_utc: string;
  after_file: string; before_file: string | null;
  status: { state: "queued" | "running" | "done" | "failed"; step?: string; error?: string; assessment_id?: string; alerts?: number };
}

export const DISASTER_TYPES = ["earthquake", "fire", "flooding", "wind", "tsunami", "volcano", "other"];

export interface BuildingProps {
  building_id: string; predicted_class: DamageClass | null; class_probabilities: Record<DamageClass, number>;
  confidence: number; review_status: "auto" | "needs_review"; reason_codes: string[]; true_class: DamageClass | null;
  model_id: string; inference_mode: string; centroid_px: [number, number]; centroid_lnglat: [number, number] | null;
  localized_fraction: number | null; area_m2?: number;
}

export interface Feature {
  type: "Feature"; id: string; properties: BuildingProps;
  geometry: { type: "Polygon"; coordinates: number[][][] } | { type: "MultiPolygon"; coordinates: number[][][][] };
}

export interface Zone {
  zone_id: string; buildings: number; counts: Record<DamageClass, number>; priority: number;
  centroid_px: [number, number]; centroid_lat: number; centroid_lon: number; hull_px: [number, number][];
  member_ids: string[];
}

export interface Summary {
  buildings: number; assessed: number; needs_review: number; coverage: number;
  predicted: Record<DamageClass | "not-detected", number>; truth: Record<DamageClass | "un-classified", number>;
  severe_assessed: number; severe_share: number;
  vs_truth: { buildings_compared?: number; accuracy?: number; macro_f1_present_classes?: number; confusion?: number[][] };
}

export interface Alert {
  alert_id: string; severity: "high" | "medium"; status: string; rule: string;
  severe_area_m2: number; building_area_m2: number; severe_share: number; structures: number; severe: number;
  counts: Record<DamageClass, number>; centroid_px: [number, number]; centroid_lat: number; centroid_lon: number;
  area_m2: number; hull_px: [number, number][]; member_ids: string[];
}

export interface Benchmark {
  xbd_buildings: number; xbd_found: number; recall: number; detections: number; detections_on_buildings: number;
  precision: number; note: string;
}

export interface Assessment {
  id: string; kind?: "area"; pair_id: string; created_utc: string; scene: Scene;
  alerts?: Alert[]; alert_rule?: string; benchmark?: Benchmark; below_threshold?: unknown[];
  model: { id: string; label: string; kind: string; mode: string; run: string; checkpoint: string; git_commit: string; epoch: number; arch: string };
  review_confidence_threshold: number; summary: Summary; zones: Zone[];
  isolated_severe: { building_id: string; predicted_class: DamageClass; centroid_px: [number, number]; centroid_lat: number; centroid_lon: number }[];
  scene_metrics: { xview2?: { score: number; loc_f1: number; dmg_f1: number } };
  has_damage_map: boolean; features: Feature[];
}

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const text = await r.text();
    let detail = text;
    try { detail = JSON.parse(text).detail ?? text; } catch { /* plain text */ }
    throw new Error(String(detail).slice(0, 300));
  }
  return r.json() as Promise<T>;
}

export const api = {
  models: () => fetch("/api/models").then(json<ModelInfo[]>),
  scene: (pair_id: string) => fetch(`/api/scenes/${pair_id}`).then(json<Scene>),
  scenes: (split = "hold") => fetch(`/api/scenes?split=${split}`).then(json<{ disasters: string[]; scenes: Scene[] }>),
  assess: async (pair_id: string, model_id: string): Promise<Assessment> => {
    const r = await fetch("/api/assess", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pair_id, model_id }),
    }).then(json<{ id: string }>);
    return fetch(`/api/assessments/${r.id}`).then(json<Assessment>);
  },
  assessArea: async (pair_id: string, model_id: string): Promise<Assessment> => {
    const r = await fetch("/api/assess-area", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pair_id, model_id }),
    }).then(json<{ id: string }>);
    return fetch(`/api/assessments/${r.id}`).then(json<Assessment>);
  },
  assessment: (aid: string) => fetch(`/api/assessments/${aid}`).then(json<Assessment>),
  uploads: () => fetch("/api/uploads").then(json<Upload[]>),
  upload: (form: FormData) => fetch("/api/uploads", { method: "POST", body: form }).then(json<Upload>),
  imageUrl: (pair_id: string, phase: "pre" | "post") => `/api/scenes/${pair_id}/image/${phase}`,
  cropUrl: (aid: string, fid: string, phase: "pre" | "post") => `/api/assessments/${aid}/features/${fid}/crop/${phase}`,
  damageMapUrl: (id: string) => `/api/assessments/${id}/damage-map`,
  reportUrl: (id: string, fmt: "html" | "md") => `/api/assessments/${id}/report.${fmt}`,
};

export const pct = (x: number | undefined, d = 0) => (x === undefined ? "–" : `${(x * 100).toFixed(d)}%`);

/** "hurricane-harvey" -> "Hurricane Harvey" */
export const titleCase = (s: string) => s.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
/** "hurricane-harvey_00000149" -> "00000149" */
export const tileNo = (pairId: string) => pairId.split("_").pop() ?? pairId;
