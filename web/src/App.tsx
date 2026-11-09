import { useEffect, useMemo, useState } from "react";
import { Alert, api, Assessment, bestUnet, Context, EventSummary, ModelInfo, Reviews, ReviewStatus, Scene, tileNo, titleCase, Upload, User } from "./api";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import ScenePanel from "./components/ScenePanel";
import UploadDialog from "./components/UploadDialog";
import AlignView, { Steps } from "./components/AlignView";
import AssessmentList, { StatusBadge } from "./components/AssessmentList";
import { Section } from "./components/AppShell";
import { Button, IconButton, Modal, Notice } from "./ui";
import DamageMap, { MapOptions } from "./components/DamageMap";
import SummaryPanel from "./components/SummaryPanel";
import AlertsPanel from "./components/AlertsPanel";
import EventView, { EventList } from "./components/EventView";
import BuildingInspector from "./components/BuildingInspector";

export type Focus = { x: number; y: number; zoom: number; key: number } | null;
export type Mode = "area" | "building";
type Source = "xbd" | "upload" | "events";

// Area alerts need no building inventory (full-image U-Net); the building check needs xBD outlines.
const preferred = (models: ModelInfo[], mode: Mode) =>
  mode === "area"
    ? bestUnet(models)?.id
    : models.find((m) => m.id === "clf_B")?.id ?? models[0]?.id;

const pending = (u: Upload) => u.status.state === "queued" || u.status.state === "running";

const SOURCE: Record<string, Source> = { assessments: "upload", events: "events", benchmark: "xbd" };

/** The damage-assessment sections (assessments, events, model check) inside the one application frame. */
export function Workspace({ user, section, visit, onSection, onCrumb }:
  { user: User; section: Section; visit: number; onSection: (s: Section) => void; onCrumb: (c: string | null) => void }) {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [mode, setMode] = useState<Mode>("area");
  const [modelId, setModelId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [disasters, setDisasters] = useState<string[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [source, setSource] = useState<Source>(SOURCE[section] ?? "upload");
  const [editing, setEditing] = useState<"rename" | "delete" | null>(null);
  const [newName, setNewName] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [uploadsLoaded, setUploadsLoaded] = useState(false);
  const [uploadId, setUploadId] = useState<string | null>(null);
  const [dialog, setDialog] = useState(false);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const [opts, setOpts] = useState<MapOptions>({ phase: "post", damage: true, compare: false, mismatches: false, zones: true, pixelMap: false, satellite: false, satelliteOpacity: 0.92, facilities: true });
  const [alertId, setAlertId] = useState<string | null>(null);
  const [reviews, setReviews] = useState<Reviews | null>(null);
  const [context, setContext] = useState<Context | null>(null);
  const [contextTick, setContextTick] = useState(0);
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [eventName, setEventName] = useState<string | null>(null);

  useEffect(() => {
    api.uploads().then((u) => { setUploads(u); setUploadsLoaded(true); }).catch((e) => { setError(String(e)); setUploadsLoaded(true); });
    Promise.all([api.models(), api.scenes("hold")])
      .then(([m, s]) => {
        setModels(m);
        setModelId(preferred(m, "area") ?? null);
        setScenes(s.scenes);
        setDisasters(s.disasters);
        const first = [...s.scenes].sort((a, b) => b.severe_true - a.severe_true)[0];
        if (first) setSceneId(first.pair_id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  // While an upload is being processed, refresh the list every 2 s.
  useEffect(() => {
    if (!uploads.some(pending)) return;
    const t = setTimeout(() => api.uploads().then(setUploads).catch(() => undefined), 2000);
    return () => clearTimeout(t);
  }, [uploads]);

  const modeModels = useMemo(() => models.filter((m) => mode === "building" || m.kind === "unet"), [models, mode]);
  const upload = uploads.find((u) => u.id === uploadId) ?? null;
  const uploadAid = upload?.status.state === "done" ? upload.status.assessment_id ?? null : null;

  const switchMode = (m: Mode) => {
    setMode(m);
    if (!models.some((x) => x.id === modelId && (m === "building" || x.kind === "unet"))) setModelId(preferred(models, m) ?? null);
  };

  const switchSource = (s: Source) => {
    setSource(s);
    setSelected(null);
    setAssessment(null);
    setLoading(false);       // a load abandoned by this switch must not leave the panels on "Detecting damage…"
    setError(null);
    if (s === "upload") switchMode("area");
  };

  // Benchmark tiles: run (or fetch cached) assessment for the chosen tile and model.
  useEffect(() => {
    if (source !== "xbd" || !sceneId || !modelId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    (mode === "area" ? api.assessArea(sceneId, modelId) : api.assess(sceneId, modelId))
      // results cached before georeferencing was added to the record get it from the scene
      .then(async (a) => (a.scene.geotransform ? a : { ...a, scene: { ...a.scene, ...(await api.scene(a.pair_id)) } }))
      .then((a) => { if (!cancelled) { setAssessment(a); setOpts((o) => ({ ...o, compare: mode === "building" && o.compare, mismatches: mode === "building" && o.mismatches })); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [source, sceneId, modelId, mode]);

  // Uploads: the assessment exists once processing is done.
  useEffect(() => {
    if (source !== "upload") return;
    setSelected(null);
    if (!uploadAid) { setAssessment(null); setLoading(false); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.assessment(uploadAid)
      .then((a) => { if (!cancelled) { setAssessment(a); setOpts((o) => ({ ...o, compare: false, mismatches: false })); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [source, uploadAid]);

  // Analyst reviews and nearby facilities belong to the assessment on screen.
  const aid = assessment?.kind === "area" ? assessment.id : null;
  useEffect(() => {
    setAlertId(null);
    setReviews(null);
    setContext(null);
    if (!aid) return;
    let cancelled = false;
    api.reviews(aid).then((r) => { if (!cancelled) setReviews(r); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [aid]);
  useEffect(() => {
    if (!aid) return;
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    const poll = () => api.context(aid).then((c) => {
      if (cancelled) return;
      setContext(c);
      if (c.available === null) timer = setTimeout(poll, 5000);
    }).catch(() => undefined);
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [aid, contextTick]);

  const review = async (id: string, status: ReviewStatus, note: string) => {
    if (!aid) return;
    const e = await api.review(aid, id, status, note);
    setReviews((r) => r && { alerts: { ...r.alerts, [id]: { status: e.status, note: e.note, reviewed_by: e.reviewed_by, reviewed_utc: e.reviewed_utc, history: e.history, proposed_by: e.proposed_by } }, counts: e.counts });
  };

  const rename = async (id: string, name: string) => {
    const u = await api.editUpload(id, { name });
    setUploads((xs) => xs.map((x) => (x.id === id ? u : x)));
    setAssessment((a) => (a && a.pair_id === id ? { ...a, scene: { ...a.scene, name: u.name, disaster: u.name } } : a));
  };
  const remove = async (id: string) => {
    await api.deleteUpload(id);
    setUploads((xs) => xs.filter((x) => x.id !== id));
    if (uploadId === id) { setUploadId(null); setAssessment(null); }
  };

  const loadEvents = () => { const m = bestUnet(models); if (m) api.events(m.id).then(setEvents).catch((e) => setError(String(e))); };
  useEffect(() => { if (source === "events") loadEvents(); }, [source, models]);
  const openTile = (pairId: string) => { onSection("benchmark"); setMode("area"); setSceneId(pairId); setSelected(null); setAssessment(null); };

  const building = useMemo(() => assessment?.features.find((f) => f.id === selected) ?? null, [assessment, selected]);
  const zoomTo = (p: { centroid_px: [number, number] }) => setFocus({ x: p.centroid_px[0], y: p.centroid_px[1], zoom: 1, key: Date.now() });
  const openAlert = (a: Alert) => { setAlertId(a.alert_id); zoomTo(a); };

  // the navigation decides the section; a click on it (or on its crumb) goes back to the section's start
  useEffect(() => {
    const s = SOURCE[section];
    if (s && s !== source) switchSource(s);
    if (section === "assessments") { setUploadId(null); setAssessment(null); }
  }, [section, visit]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    onCrumb(section === "assessments" ? upload?.name ?? null : section === "events" ? (eventName ? titleCase(eventName) : null)
      : assessment && source === "xbd" ? `${titleCase(assessment.scene.disaster)} · tile ${tileNo(assessment.pair_id)}` : null);
  }, [section, upload?.name, eventName, assessment?.pair_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const mapAndPanel = (message?: string) => (
    <>
      <DamageMap
        assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts} message={message}
        selected={selected} onSelect={setSelected} focus={focus} mode={mode} scenes={scenes}
        onScene={(id) => { onSection("benchmark"); setSceneId(id); }} reviews={reviews} alertId={alertId} context={context}
        onAssessment={(a) => { setAssessment(a); setContext(null); setContextTick((t) => t + 1); }}
      />
      <aside className="detail">
        {building && assessment ? (
          <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
        ) : mode === "area" ? (
          <AlertsPanel assessment={assessment} loading={loading || (!!upload && pending(upload))} onAlert={openAlert}
            alertId={alertId} reviews={reviews} onReview={review} context={context} user={user} />
        ) : (
          <SummaryPanel assessment={assessment} loading={loading} onZone={zoomTo} onBuilding={setSelected} />
        )}
      </aside>
    </>
  );

  const created = (u: Upload) => { setDialog(false); setUploads((xs) => [u, ...xs.filter((x) => x.id !== u.id)]); setUploadId(u.id); };
  const dialogEl = dialog && <UploadDialog models={models} onClose={() => setDialog(false)} onCreated={created} />;

  if (section === "events") {
    return (
      <div className="work-grid events">
        <nav className="sidebar" aria-label="Events"><EventList events={events} selected={eventName} onSelect={setEventName} model={bestUnet(models)} /></nav>
        <EventView disaster={eventName} modelId={bestUnet(models)?.id ?? null} onTile={openTile} onChanged={loadEvents} />
      </div>
    );
  }

  if (section === "benchmark") {
    return (
      <div className="work-col">
        <div className="work-head">
          <div className="work-title"><h1>Model check</h1><p>Benchmark tiles with known damage, to see how well each model does.</p></div>
          <div className="work-tools">
            <div className="segmented" role="group" aria-label="Mode">
              <button aria-pressed={mode === "area"} onClick={() => switchMode("area")}>Area alerts</button>
              <button aria-pressed={mode === "building"} onClick={() => switchMode("building")}>Building check</button>
            </div>
            <label className="field-inline">Model
              <select value={modelId ?? ""} onChange={(e) => setModelId(e.target.value)} aria-label="Model">
                {modeModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
          </div>
        </div>
        <div className="work-grid three">
          <nav className="sidebar" aria-label="Benchmark tiles"><ScenePanel scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId} /></nav>
          {mapAndPanel()}
        </div>
      </div>
    );
  }

  // Assessments: the list, or one assessment (alignment check, progress, or the results)
  if (!upload) {
    return (
      <div className="work-page">
        <AssessmentList uploads={uploads} loading={!uploadsLoaded} onOpen={setUploadId} onNew={() => setDialog(true)} />
        {dialogEl}
      </div>
    );
  }
  const st = upload.status;
  const startEdit = (m: "rename" | "delete") => { setEditing(m); setNewName(upload.name); setActionError(null); };
  const runEdit = async () => {
    setActionError(null);
    try { if (editing === "rename") await rename(upload.id, newName); else await remove(upload.id); setEditing(null); }
    catch (e) { setActionError(String(e).replace(/^Error: /, "")); }
  };
  return (
    <div className="work-col">
      <div className="work-head">
        <div className="work-title row">
          <IconButton icon={ArrowLeft} label="All assessments" onClick={() => setUploadId(null)} />
          <div>
            <h1>{upload.name}</h1>
            <p>{titleCase(upload.disaster_type)}{upload.event_date ? ` · event ${upload.event_date}` : ""} · uploaded {upload.created_utc.slice(0, 10)}</p>
          </div>
          <StatusBadge u={upload} />
        </div>
        <div className="work-tools">
          <IconButton icon={Pencil} label="Rename" onClick={() => startEdit("rename")} />
          <IconButton icon={Trash2} tone="danger" label={pending(upload) ? "Wait until processing has finished" : "Delete"} disabled={pending(upload)} onClick={() => startEdit("delete")} />
        </div>
      </div>
      {st.state === "review" ? (
        <AlignView key={upload.id} upload={upload} onConfirmed={(u) => setUploads((xs) => xs.map((x) => (x.id === u.id ? u : x)))} />
      ) : st.state === "done" ? (
        <div className="work-grid two">{mapAndPanel()}</div>
      ) : (
        <div className="work-message">
          <section className="card progress-card">
            <Steps current={st.state === "failed" ? 2 : 2} />
            {st.state === "failed"
              ? <Notice tone="error">The assessment failed: {st.error}</Notice>
              : <><div className="spinner" aria-hidden /><h2>{st.state === "queued" ? "Waiting to start" : st.step || "Working"}…</h2>
                <p className="subtle">Detecting buildings and damage takes about a minute per square kilometre. You can leave this page; the result appears in the list.</p></>}
          </section>
        </div>
      )}
      <Modal open={editing !== null} title={editing === "rename" ? "Rename assessment" : "Delete assessment"} onClose={() => setEditing(null)}
        footer={<><Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant={editing === "delete" ? "danger" : "primary"} onClick={() => void runEdit()}>{editing === "rename" ? "Save" : "Delete"}</Button></>}>
        {editing === "rename"
          ? <label className="field"><span>Name</span><input type="text" value={newName} maxLength={80} autoFocus onChange={(e) => setNewName(e.target.value)} /></label>
          : <p>Delete <strong>{upload.name}</strong> with its images, alerts and reviews? This cannot be undone.</p>}
        {actionError && <Notice tone="error">{actionError}</Notice>}
      </Modal>
      {dialogEl}
    </div>
  );
}
