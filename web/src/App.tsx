import { useEffect, useMemo, useState } from "react";
import { Alert, api, Assessment, bestUnet, Context, EventSummary, ModelInfo, Reviews, ReviewStatus, Scene, tileNo, titleCase, Upload } from "./api";
import ScenePanel from "./components/ScenePanel";
import UploadPanel from "./components/UploadPanel";
import UploadDialog from "./components/UploadDialog";
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

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [mode, setMode] = useState<Mode>("area");
  const [modelId, setModelId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [disasters, setDisasters] = useState<string[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [source, setSource] = useState<Source>("xbd");
  const [uploads, setUploads] = useState<Upload[]>([]);
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
  const [events, setEvents] = useState<EventSummary[]>([]);
  const [eventName, setEventName] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.models(), api.scenes("hold"), api.uploads()])
      .then(([m, s, u]) => {
        setModels(m);
        setModelId(preferred(m, "area") ?? null);
        setScenes(s.scenes);
        setDisasters(s.disasters);
        setUploads(u);
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
  }, [aid]);

  const review = async (id: string, status: ReviewStatus, note: string) => {
    if (!aid) return;
    const e = await api.review(aid, id, status, note);
    setReviews((r) => r && { alerts: { ...r.alerts, [id]: { status: e.status, note: e.note, reviewed_by: e.reviewed_by, reviewed_utc: e.reviewed_utc } }, counts: e.counts });
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
  const openTile = (pairId: string) => { setSource("xbd"); setMode("area"); setSceneId(pairId); setSelected(null); setAssessment(null); };

  const building = useMemo(() => assessment?.features.find((f) => f.id === selected) ?? null, [assessment, selected]);
  const zoomTo = (p: { centroid_px: [number, number] }) => setFocus({ x: p.centroid_px[0], y: p.centroid_px[1], zoom: 1, key: Date.now() });
  const openAlert = (a: Alert) => { setAlertId(a.alert_id); zoomTo(a); };

  const uploadMessage = source !== "upload" ? undefined
    : !upload ? "Select an upload, or upload imagery"
      : upload.status.state === "failed" ? `Upload failed: ${upload.status.error}`
        : pending(upload) ? `${upload.status.state === "queued" ? "Queued" : upload.status.step ?? "Processing"}…` : undefined;

  return (
    <div className="app">
      <header className="header">
        <span className="wordmark">EnviroSense</span>
        <nav className="crumbs" aria-label="Location">
          {source === "xbd" ? (
            <>
              <span>xBD hold set</span>
              {assessment && (<><span className="slash">/</span><span>{titleCase(assessment.scene.disaster)}</span>
                <span className="slash">/</span><span>Tile {tileNo(assessment.pair_id)}</span></>)}
            </>
          ) : source === "events" ? (
            <>
              <span>Events</span>
              {eventName && (<><span className="slash">/</span><span>{titleCase(eventName)}</span></>)}
            </>
          ) : (
            <>
              <span>Uploads</span>
              {upload && (<><span className="slash">/</span><span>{upload.name}</span></>)}
            </>
          )}
        </nav>
        <div className="spacer" />
        <div className="segmented" role="group" aria-label="Mode">
          <button aria-pressed={mode === "area"} onClick={() => switchMode("area")}>Area alerts</button>
          <button aria-pressed={mode === "building"} onClick={() => switchMode("building")} disabled={source === "upload"}
            title={source === "upload" ? "The building check needs building outlines; uploads use area alerts" : undefined}>
            Building check
          </button>
        </div>
        <label className="field-inline">
          Model
          {source === "upload" ? (
            <select value={assessment?.model.id ?? ""} disabled aria-label="Model">
              <option value={assessment?.model.id ?? ""}>{assessment?.model.label ?? models.find((m) => m.id === upload?.model_id)?.label ?? "–"}</option>
            </select>
          ) : (
            <select value={modelId ?? ""} onChange={(e) => setModelId(e.target.value)} aria-label="Model">
              {modeModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
          )}
        </label>
      </header>
      <div className="body">
        <nav className="sidebar" aria-label="Imagery">
          <div className="sidebar-tabs">
            <div className="segmented" role="group" aria-label="Imagery source">
              <button aria-pressed={source === "xbd"} onClick={() => switchSource("xbd")}>Benchmark tiles</button>
              <button aria-pressed={source === "upload"} onClick={() => switchSource("upload")}>
                Uploads{uploads.length > 0 && <span className="tab-count">{uploads.length}</span>}
              </button>
              <button aria-pressed={source === "events"} onClick={() => switchSource("events")}>Events</button>
            </div>
          </div>
          {source === "xbd"
            ? <ScenePanel scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId} />
            : source === "upload"
              ? <UploadPanel uploads={uploads} uploadId={uploadId} onUpload={setUploadId} onNew={() => setDialog(true)} onRename={rename} onDelete={remove} />
              : <EventList events={events} selected={eventName} onSelect={setEventName} model={bestUnet(models)} />}
        </nav>
        {source === "events" ? (
          <EventView disaster={eventName} modelId={bestUnet(models)?.id ?? null} onTile={openTile} onChanged={loadEvents} />
        ) : (
          <>
            <DamageMap
              assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts} message={uploadMessage}
              selected={selected} onSelect={setSelected} focus={focus} mode={mode} scenes={scenes}
              onScene={(id) => { switchSource("xbd"); setSceneId(id); }} reviews={reviews} alertId={alertId} context={context}
            />
            <aside className="detail">
              {building && assessment ? (
                <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
              ) : mode === "area" ? (
                <AlertsPanel assessment={assessment} loading={loading || (!!upload && pending(upload))} onAlert={openAlert}
                  alertId={alertId} reviews={reviews} onReview={review} context={context} />
              ) : (
                <SummaryPanel assessment={assessment} loading={loading} onZone={zoomTo} onBuilding={setSelected} />
              )}
            </aside>
          </>
        )}
      </div>
      {dialog && (
        <UploadDialog models={models} onClose={() => setDialog(false)}
          onCreated={(u) => { setDialog(false); setUploads((xs) => [u, ...xs.filter((x) => x.id !== u.id)]); switchSource("upload"); setUploadId(u.id); }} />
      )}
    </div>
  );
}
