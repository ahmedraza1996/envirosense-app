import { useEffect, useMemo, useState } from "react";
import { api, Assessment, ModelInfo, Scene, tileNo, titleCase } from "./api";
import ScenePanel from "./components/ScenePanel";
import DamageMap, { MapOptions } from "./components/DamageMap";
import SummaryPanel from "./components/SummaryPanel";
import AlertsPanel from "./components/AlertsPanel";
import BuildingInspector from "./components/BuildingInspector";

export type Focus = { x: number; y: number; zoom: number; key: number } | null;
export type Mode = "area" | "building";

// Area alerts need no building inventory (full-image U-Net); the building check needs xBD outlines.
const preferred = (models: ModelInfo[], mode: Mode) =>
  mode === "area"
    ? (models.find((m) => m.id === "unet_early") ?? models.find((m) => m.kind === "unet"))?.id
    : models.find((m) => m.id === "clf_B")?.id ?? models[0]?.id;

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [mode, setMode] = useState<Mode>("area");
  const [modelId, setModelId] = useState<string | null>(null);
  const [scenes, setScenes] = useState<Scene[]>([]);
  const [disasters, setDisasters] = useState<string[]>([]);
  const [sceneId, setSceneId] = useState<string | null>(null);
  const [assessment, setAssessment] = useState<Assessment | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus>(null);
  const [opts, setOpts] = useState<MapOptions>({ phase: "post", damage: true, compare: false, mismatches: false, zones: true, pixelMap: false });

  useEffect(() => {
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

  const modeModels = useMemo(() => models.filter((m) => mode === "building" || m.kind === "unet"), [models, mode]);

  const switchMode = (m: Mode) => {
    setMode(m);
    if (!models.some((x) => x.id === modelId && (m === "building" || x.kind === "unet"))) setModelId(preferred(models, m) ?? null);
  };

  useEffect(() => {
    if (!sceneId || !modelId) return;
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
  }, [sceneId, modelId, mode]);

  const building = useMemo(() => assessment?.features.find((f) => f.id === selected) ?? null, [assessment, selected]);
  const zoomTo = (p: { centroid_px: [number, number] }) => setFocus({ x: p.centroid_px[0], y: p.centroid_px[1], zoom: 1, key: Date.now() });

  return (
    <div className="app">
      <header className="header">
        <span className="wordmark">EnviroSense</span>
        <nav className="crumbs" aria-label="Location">
          <span>xBD hold set</span>
          {assessment && (<><span className="slash">/</span><span>{titleCase(assessment.scene.disaster)}</span>
            <span className="slash">/</span><span>Tile {tileNo(assessment.pair_id)}</span></>)}
        </nav>
        <div className="spacer" />
        <div className="segmented" role="group" aria-label="Mode">
          <button aria-pressed={mode === "area"} onClick={() => switchMode("area")}>Area alerts</button>
          <button aria-pressed={mode === "building"} onClick={() => switchMode("building")}>Building check</button>
        </div>
        <label className="field-inline">
          Model
          <select value={modelId ?? ""} onChange={(e) => setModelId(e.target.value)} aria-label="Model">
            {modeModels.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
      </header>
      <div className="body">
        <ScenePanel scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId} />
        <DamageMap
          assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts}
          selected={selected} onSelect={setSelected} focus={focus} mode={mode} scenes={scenes} onScene={setSceneId}
        />
        <aside className="detail">
          {building && assessment ? (
            <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
          ) : mode === "area" ? (
            <AlertsPanel assessment={assessment} loading={loading} onAlert={zoomTo} />
          ) : (
            <SummaryPanel assessment={assessment} loading={loading} onZone={zoomTo} onBuilding={setSelected} />
          )}
        </aside>
      </div>
    </div>
  );
}
