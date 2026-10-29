import { useEffect, useMemo, useState } from "react";
import { api, Assessment, ModelInfo, Scene } from "./api";
import ScenePanel from "./components/ScenePanel";
import DamageMap, { MapOptions } from "./components/DamageMap";
import SummaryPanel from "./components/SummaryPanel";
import BuildingInspector from "./components/BuildingInspector";

export type Focus = { x: number; y: number; zoom: number; key: string } | null;

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
  const [opts, setOpts] = useState<MapOptions>({ phase: "post", showTruth: false, errorsOnly: false, showZones: true, damageMap: false });

  useEffect(() => {
    Promise.all([api.models(), api.scenes("hold")])
      .then(([m, s]) => {
        setModels(m);
        setScenes(s.scenes);
        setDisasters(s.disasters);
        const demo = [...s.scenes].sort((a, b) => b.severe_true - a.severe_true)[0];
        if (demo) setSceneId(demo.pair_id);
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
      .then((a) => { if (!cancelled) { setAssessment(a); setOpts((o) => ({ ...o, damageMap: o.damageMap && a.has_damage_map })); } })
      .catch((e) => { if (!cancelled) setError(String(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [sceneId, modelId]);

  const building = useMemo(
    () => assessment?.features.find((f) => f.id === selected) ?? null,
    [assessment, selected],
  );
  const model = models.find((m) => m.id === modelId);

  return (
    <div className="app">
      <div className="top">
        <div className="brand"><span className="logo" />EnviroSense · damage assessment</div>
        <div className="sep" />
        {model && <span className="chip acc">Model <b>{model.label}</b></span>}
        {assessment && <span className="chip">Scene <b>{assessment.scene.disaster}</b>&nbsp;{assessment.pair_id.split("_").pop()}</span>}
        <div className="grow" />
        <span className="chip amb">xBD hold split · tiles unseen in training</span>
      </div>
      <div className="body">
        <ScenePanel
          models={models} modelId={modelId} onModel={setModelId}
          scenes={scenes} disasters={disasters} sceneId={sceneId} onScene={setSceneId}
        />
        <DamageMap
          assessment={assessment} loading={loading} error={error} options={opts} onOptions={setOpts}
          selected={selected} onSelect={setSelected} focus={focus}
        />
        <div className="panel r">
          {building && assessment ? (
            <BuildingInspector assessment={assessment} feature={building} onBack={() => setSelected(null)} />
          ) : (
            <SummaryPanel
              assessment={assessment} loading={loading}
              onZone={(z) => setFocus({ x: z.centroid_px[0], y: z.centroid_px[1], zoom: 1, key: z.zone_id + Date.now() })}
              onBuilding={(id) => setSelected(id)}
            />
          )}
        </div>
      </div>
    </div>
  );
}
