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
// "Before" view: footprints the model found, drawn neutrally. Damage is only read, and only coloured, on the After image.
export const FOOTPRINT_COLOUR = "#2457A6";

export interface ModelInfo { id: string; label: string; kind: "classifier" | "unet"; run: string; test_score: number | null; approved_default?: boolean }

/** Default full-image model for area alerts and uploads: the approved one (governance/approved_model.json); the best xView2 test
 *  score is used only when no approval exists. */
export const bestUnet = (models: ModelInfo[]) =>
  models.find((m) => m.kind === "unet" && m.approved_default)
  ?? models.filter((m) => m.kind === "unet").sort((a, b) => (b.test_score ?? 0) - (a.test_score ?? 0))[0];

export interface Scene {
  pair_id: string; split: string; disaster: string; disaster_type: string; buildings: number;
  true_none: number; true_minor: number; true_major: number; true_destroyed: number; true_unclassified: number;
  severe_true: number; pre_date?: string; post_date?: string;
  centre_lat?: number; centre_lon?: number; pixel_size_m?: number; geotransform?: number[]; size_px?: number;
  // uploads only
  source?: "upload"; name?: string; width_px?: number; height_px?: number; event_date?: string | null;
  before?: BeforeInfo; notes?: string[];
  geo_bounds?: [[number, number], [number, number]] | null;   // rotated geotransform: bounds of the north-up copies
  geo_fit_error_m?: number;
  geo_offset_m?: GeoOffset | null;           // placement on the street map moved by hand or from OpenStreetMap
}

export interface GeoOffset { east: number; north: number; method: string | null; note?: string }
export interface GeoSuggestion {
  east_m: number; north_m: number; buildings: number; sharpness: number; before_after_disagree_m: number; clear: boolean; note: string;
}

export interface BeforeInfo {
  kind: "archive" | "upload"; archive?: string; file?: string;
  tiles?: { tile: string; capture_date: string; covers: number }[];
  coverage: number; shift_px: [number, number] | null; shift_m: number | null; response: number | null; corrected: boolean;
  method?: string | null; rotation_deg?: number; scale?: number; matches?: number | null; inliers?: number | null;
}

export interface Upload {
  id: string; name: string; disaster_type: string; event_date: string | null; model_id: string; created_utc: string;
  after_file: string; before_file: string | null;
  status: { state: "queued" | "running" | "done" | "failed"; step?: string; error?: string; assessment_id?: string; alerts?: number };
}

export type ReviewStatus = "pending" | "proposed" | "confirmed" | "dismissed" | "needs_info" | "retracted";
export const REVIEW_LABEL: Record<ReviewStatus, string> = {
  pending: "Draft", proposed: "Awaiting approval", confirmed: "Confirmed", dismissed: "Dismissed", needs_info: "Needs information", retracted: "Retracted",
};
export interface ReviewHistoryItem { status: ReviewStatus; note: string; by: string; utc: string; role?: string }
export interface ReviewEntry { status: ReviewStatus; note: string; reviewed_by: string | null; reviewed_utc: string | null; history?: ReviewHistoryItem[]; proposed_by?: string | null }
export interface Gate { code: string; level: "info" | "warn"; message: string }

export interface Reviews { alerts: Record<string, ReviewEntry>; counts: Record<ReviewStatus, number> }

export interface AlertContext {
  inside: { kind: string; name: string | null }[];
  within_1km: Record<string, number>;
  nearest_hospital: { name: string | null; distance_m: number } | null;
  nearest_main_road: { class: string; name: string | null; distance_m: number } | null;
  flags: string[];
}
export interface Facility { kind: string; name: string | null; lat: number; lon: number; id: string }
export interface Context {
  available: boolean | null; state?: string; error?: string; source?: string; fetched_utc?: string;
  facilities: Facility[]; alerts: Record<string, AlertContext>;
}

export interface EventSummary { disaster: string; disaster_type: string; tiles: number; assessed: number; alerts: number; xbd_severe: number }
export interface EventTile {
  pair_id: string; tile: string; centre_lat: number; centre_lon: number; xbd_buildings: number; xbd_severe: number;
  assessed: boolean; rank: number | null; alerts?: number; high?: number; medium?: number; severe_m2?: number; structures?: number;
}
export interface EventJob { state: "idle" | "running" | "done" | "failed"; disaster?: string; done?: number; total?: number; current?: string | null; error?: string }
export interface EventDetail {
  disaster: string; model_id: string; tiles: EventTile[]; rank_agreement_with_xbd: number | null; job: EventJob;
  alerts: { pair_id: string; alert_id: string; severity: "high" | "medium"; severe_m2: number; ring: [number, number][] }[];
  frames: { pair_id: string; assessed: boolean; ring: [number, number][] }[];
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
  low_confidence_structures?: number; low_confidence_share?: number;
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
  has_damage_map: boolean; features: Feature[]; gates?: Gate[];
}

async function json<T>(r: Response): Promise<T> {
  if (r.status === 401) window.dispatchEvent(new Event("auth-expired"));
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
      method: "POST", headers: { "Content-Type": "application/json", }, body: JSON.stringify({ pair_id, model_id }),
    }).then(json<{ id: string }>);
    return fetch(`/api/assessments/${r.id}`).then(json<Assessment>);
  },
  assessArea: async (pair_id: string, model_id: string): Promise<Assessment> => {
    const r = await fetch("/api/assess-area", {
      method: "POST", headers: { "Content-Type": "application/json", }, body: JSON.stringify({ pair_id, model_id }),
    }).then(json<{ id: string }>);
    return fetch(`/api/assessments/${r.id}`).then(json<Assessment>);
  },
  setGeoOffset: (aid: string, east_m: number, north_m: number, method: string, note?: string) =>
    fetch(`/api/assessments/${aid}/geo-offset`, { method: "PUT", headers: { "Content-Type": "application/json", }, body: JSON.stringify({ east_m, north_m, method, note }) }).then(json<GeoOffset>),
  measureGeoOffset: (aid: string) => fetch(`/api/assessments/${aid}/geo-offset/measure`, { method: "POST" }).then(json<GeoSuggestion>),
  assessment: (aid: string) => fetch(`/api/assessments/${aid}`).then(json<Assessment>),
  policy: () => fetch("/api/policy").then(json<{ upload_retention_days: number | null; notice: string }>),
  uploads: () => fetch("/api/uploads").then(json<Upload[]>),
  upload: (form: FormData) => fetch("/api/uploads", { method: "POST", body: form }).then(json<Upload>),
  reviews: (aid: string) => fetch(`/api/assessments/${aid}/reviews`).then(json<Reviews>),
  review: (aid: string, alertId: string, status: ReviewStatus, note: string) =>
    fetch(`/api/assessments/${aid}/alerts/${alertId}/review`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, note }),
    }).then(json<ReviewEntry & { counts: Record<ReviewStatus, number> }>),
  context: (aid: string) => fetch(`/api/assessments/${aid}/context`).then(json<Context>),
  exportUrl: (aid: string, kind: "alerts.geojson" | "structures.geojson" | "csv", include?: string) =>
    kind === "csv" ? `/api/assessments/${aid}/export.csv${include ? `?include=${include}` : ""}`
      : `/api/assessments/${aid}/export.geojson?layer=${kind.split(".")[0]}${include ? `&include=${include}` : ""}`,
  editUpload: (id: string, patch: { name?: string; disaster_type?: string; event_date?: string }) =>
    fetch(`/api/uploads/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json", }, body: JSON.stringify(patch) }).then(json<Upload>),
  deleteUpload: (id: string) => fetch(`/api/uploads/${id}`, { method: "DELETE" }).then(json<{ deleted: string }>),
  events: (model: string) => fetch(`/api/events?model_id=${model}`).then(json<EventSummary[]>),
  event: (disaster: string, model: string) => fetch(`/api/events/${disaster}?model_id=${model}`).then(json<EventDetail>),
  assessEvent: (disaster: string, model_id: string, limit: number) =>
    fetch(`/api/events/${disaster}/assess`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model_id, limit }) }).then(json<EventJob>),
  eventJob: () => fetch("/api/events/job").then(json<EventJob>),
  imageUrl: (pair_id: string, phase: "pre" | "post") => `/api/scenes/${pair_id}/image/${phase}`,
  cropUrl: (aid: string, fid: string, phase: "pre" | "post") => `/api/assessments/${aid}/features/${fid}/crop/${phase}`,
  geoUrl: (id: string, layer: "pre" | "post" | "damage") => `/api/assessments/${id}/geo/${layer}`,
  damageMapUrl: (id: string) => `/api/assessments/${id}/damage-map`,
  reportUrl: (id: string, fmt: "html" | "md") => `/api/assessments/${id}/report.${fmt}`,
};

export const pct = (x: number | undefined, d = 0) => (x === undefined ? "–" : `${(x * 100).toFixed(d)}%`);

/** "hurricane-harvey" -> "Hurricane Harvey" */
export const titleCase = (s: string) => s.split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
/** "hurricane-harvey_00000149" -> "00000149" */
export const tileNo = (pairId: string) => pairId.split("_").pop() ?? pairId;


// ---- accounts ---------------------------------------------------------------------------------------------------
export type Role = string;   // a role key: the four built-in roles or one an administrator created
export interface User {
  username: string; name: string; role: Role; role_label: string; unit: string; unit_name: string; unit_path: string; active: boolean;
  must_change_password: boolean; created_utc?: string; last_login_utc?: string | null; permissions: string[]; temporary_password?: string | null;
}
export interface RoleInfo { key: string; label: string; description: string; builtin: boolean; permissions: string[]; users: number }
export interface PermissionInfo { key: string; description: string; sensitive: boolean }
export interface PermissionCatalogue { permissions: PermissionInfo[]; conflicts: { a: string; b: string; reason: string }[] }
export interface UnitInfo { id: string; name: string; parent: string | null; path: string; users: number }
export interface AuditEntry { seq: number; utc: string; action: string; actor: string; assessment: string | null; detail: Record<string, unknown> }
export interface ApprovalOutcome { status: "pending" | "applied"; id: number; approvers: number }
export interface ApprovalRequest {
  id: number; kind: string; subject: string; payload: Record<string, unknown>; state: string; requested_by: string; decided_by: string | null; decision_note: string | null;
  self_approved: boolean; requested_utc: string; expires_utc: string; decided_utc: string | null; description: string; can_decide: boolean; can_withdraw: boolean;
}
export interface ApprovedModel { approval?: ApprovalOutcome; default_model: string | null; approved_utc?: string; approved_by?: string; reason?: string; previous?: string | null; available?: { id: string; label: string }[] }
export const can = (u: User, perm: string) => u.permissions.includes(perm);

const send = (method: string, url: string, body?: unknown) =>
  fetch(url, { method, headers: body === undefined ? undefined : { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });

export const accounts = {
  me: () => fetch("/api/auth/me").then(json<User>),
  login: (username: string, password: string) => send("POST", "/api/auth/login", { username, password }).then(json<User>),
  logout: () => send("POST", "/api/auth/logout").then(json<{ ok: boolean }>),
  changePassword: (current: string, next: string) => send("POST", "/api/auth/password", { current, new: next }).then(json<{ ok: boolean }>),
  users: () => fetch("/api/admin/users").then(json<User[]>),
  addUser: (u: { username: string; name: string; role: Role; unit: string; password?: string }) => send("POST", "/api/admin/users", u).then(json<User>),
  editUser: (username: string, patch: { name?: string; role?: Role; unit?: string; active?: boolean }) => send("PATCH", `/api/admin/users/${username}`, patch).then(json<User>),
  resetPassword: (username: string) => send("POST", `/api/admin/users/${username}/reset-password`).then(json<{ username: string; temporary_password: string }>),
  roles: () => fetch("/api/admin/roles").then(json<RoleInfo[]>),
  permissions: () => fetch("/api/admin/permissions").then(json<PermissionCatalogue>),
  addRole: (r: { key: string; label: string; description: string; permissions: string[]; based_on?: string }) => send("POST", "/api/admin/roles", r).then(json<RoleInfo>),
  setRolePermissions: (key: string, permissions: string[], reason: string) => send("PUT", `/api/admin/roles/${key}/permissions`, { permissions, reason }).then(json<{ approval: ApprovalOutcome }>),
  approvals: (state?: string) => fetch(`/api/approvals${state ? `?state=${state}` : ""}`).then(json<ApprovalRequest[]>),
  decideApproval: (id: number, approve: boolean, note: string) => send("POST", `/api/approvals/${id}/${approve ? "approve" : "reject"}`, { note }).then(json<ApprovalRequest>),
  withdrawApproval: (id: number) => send("POST", `/api/approvals/${id}/withdraw`).then(json<ApprovalRequest>),
  deleteRole: (key: string) => send("DELETE", `/api/admin/roles/${key}`).then(json<{ deleted: string }>),
  units: () => fetch("/api/admin/units").then(json<UnitInfo[]>),
  addUnit: (name: string, parent: string) => send("POST", "/api/admin/units", { name, parent }).then(json<UnitInfo>),
  editUnit: (id: string, patch: { name?: string; parent?: string }) => send("PATCH", `/api/admin/units/${id}`, patch).then(json<UnitInfo>),
  audit: (limit = 300, assessment?: string) => fetch(`/api/audit?limit=${limit}${assessment ? `&assessment=${encodeURIComponent(assessment)}` : ""}`).then(json<AuditEntry[]>),
  auditVerify: () => fetch("/api/audit/verify").then(json<{ ok: boolean; entries: number; first_bad_line: number | null; reason: string }>),
  approvedModel: () => fetch("/api/approved-model").then(json<ApprovedModel>),
  approveModel: (model_id: string, reason: string) => send("PUT", "/api/admin/approved-model", { model_id, reason }).then(json<ApprovedModel>),
};
