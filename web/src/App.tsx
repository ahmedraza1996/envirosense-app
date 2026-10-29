import { useEffect, useMemo, useState } from "react";
import { api, Assessment, ModelInfo, Scene, tileNo, titleCase } from "./api";
import ScenePanel from "./components/ScenePanel";
import DamageMap, { MapOptions } from "./components/DamageMap";
import SummaryPanel from "./components/SummaryPanel";
import BuildingInspector from "./components/BuildingInspector";

export type Focus = { x: number; y: number; zoom: number; key: number } | null;

export default function App() {
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [modelId, setModelId] = useState("clf_B");
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
        setScenes(s.scenes);
        setDisasters(s.disasters);
        const first = [...s.scenes].sort((a, b) => b.severe_true - a.severe_true)[0];
        if (first) setSceneId(first.pair_id);
      })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!sceneId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setSelected(null);
    api.assess(sceneId, modelId)
      .then((a) => { if (!cancelled) { setAssessment(a); setOpts((o) => ({ ...o, pixelMap: o.pixelMap && a.has_damage_map })); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sceneId, modelId]);

  const building = useMemo(() => assessment?.features.find((f) => f.id === selected) ?? null, [assessment, selected]);

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
        <label className="field-inline">
          Model
          <select value={modelId} onChange={(e) => setModelId(e.target.value)} aria-label="Model">
            {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </label>
      </header>
      <div className="body">
        <ScenePanel scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId} />
        <DamageMap
          assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts}
          selected={selected} onSelect={setSelected} focus={focus}
        />
        <aside className="detail">
          {building && assessment ? (
            <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
          ) : (
            <SummaryPanel
              assessment={assessment} loading={loading}
              onZone={(z) => setFocus({ x: z.centroid_px[0], y: z.centroid_px[1], zoom: 1, key: Date.now() })}
              onBuilding={setSelected}
            />
          )}
        </aside>
      </div>
    </div>
  );
}
