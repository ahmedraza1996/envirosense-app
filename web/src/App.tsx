import { useEffect, useMemo, useState } from "react";
import { api, Assessment, ModelInfo, Scene, tileNo, titleCase, Upload } from "./api";
import ScenePanel from "./components/ScenePanel";
import UploadPanel from "./components/UploadPanel";
import UploadDialog from "./components/UploadDialog";
import DamageMap, { MapOptions } from "./components/DamageMap";
import SummaryPanel from "./components/SummaryPanel";
import AlertsPanel from "./components/AlertsPanel";
import BuildingInspector from "./components/BuildingInspector";

export type Focus = { x: number; y: number; zoom: number; key: number } | null;
export type Mode = "area" | "building";
type Source = "xbd" | "upload";

// Area alerts need no building inventory (full-image U-Net); the building check needs xBD outlines.
const preferred = (models: ModelInfo[], mode: Mode) =>
  mode === "area"
    ? (models.find((m) => m.id === "unet_early") ?? models.find((m) => m.kind === "unet"))?.id
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
  const [opts, setOpts] = useState<MapOptions>({ phase: "post", damage: true, compare: false, mismatches: false, zones: true, pixelMap: false });

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
    if (!uploadAid) { setAssessment(null); return; }
    let cancelled = false;
    setLoading(true);
    setError(null);
    api.assessment(uploadAid)
      .then((a) => { if (!cancelled) { setAssessment(a); setOpts((o) => ({ ...o, compare: false, mismatches: false })); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [source, uploadAid]);

  const building = useMemo(() => assessment?.features.find((f) => f.id === selected) ?? null, [assessment, selected]);
  const zoomTo = (p: { centroid_px: [number, number] }) => setFocus({ x: p.centroid_px[0], y: p.centroid_px[1], zoom: 1, key: Date.now() });

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
            </div>
          </div>
          {source === "xbd"
            ? <ScenePanel scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId} />
            : <UploadPanel uploads={uploads} uploadId={uploadId} onUpload={setUploadId} onNew={() => setDialog(true)} />}
        </nav>
        <DamageMap
          assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts} message={uploadMessage}
          selected={selected} onSelect={setSelected} focus={focus} mode={mode} scenes={scenes}
          onScene={(id) => { switchSource("xbd"); setSceneId(id); }}
        />
        <aside className="detail">
          {building && assessment ? (
            <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
          ) : mode === "area" ? (
            <AlertsPanel assessment={assessment} loading={loading || (!!upload && pending(upload))} onAlert={zoomTo} />
          ) : (
            <SummaryPanel assessment={assessment} loading={loading} onZone={zoomTo} onBuilding={setSelected} />
          )}
        </aside>
      </div>
      {dialog && (
        <UploadDialog models={models} onClose={() => setDialog(false)}
          onCreated={(u) => { setDialog(false); setUploads((xs) => [u, ...xs.filter((x) => x.id !== u.id)]); switchSource("upload"); setUploadId(u.id); }} />
      )}
    </div>
  );
}
