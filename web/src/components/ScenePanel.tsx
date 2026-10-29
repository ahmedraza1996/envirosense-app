import { useMemo, useState } from "react";
import { CLASS_COLOUR, ModelInfo, Scene } from "../api";

interface Props {
  models: ModelInfo[]; modelId: string; onModel: (id: string) => void;
  scenes: Scene[]; disasters: string[]; sceneId: string | null; onScene: (id: string) => void;
}

export default function ScenePanel({ models, modelId, onModel, scenes, disasters, sceneId, onScene }: Props) {
  const [disaster, setDisaster] = useState("");
  const [sort, setSort] = useState<"severe" | "buildings" | "name">("severe");
  const list = useMemo(() => {
    const s = scenes.filter((x) => !disaster || x.disaster === disaster);
    const key = { severe: (x: Scene) => -x.severe_true, buildings: (x: Scene) => -x.buildings, name: () => 0 }[sort];
    return [...s].sort((a, b) => key(a) - key(b) || a.pair_id.localeCompare(b.pair_id));
  }, [scenes, disaster, sort]);

  return (
    <div className="panel">
      <div className="ph"><h2>Scenes</h2><div className="sub">xBD hold split · {scenes.length} scenes with buildings</div></div>
      <div className="sec">
        <div className="lbl">Model</div>
        <select value={modelId} onChange={(e) => onModel(e.target.value)}>
          {models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
        </select>
        <div className="note" style={{ marginTop: 6 }}>
          Crop classifiers grade each annotated building; U-Nets map damage over the whole image.
        </div>
      </div>
      <div className="sec">
        <div className="lbl">Disaster</div>
        <select value={disaster} onChange={(e) => setDisaster(e.target.value)}>
          <option value="">All disasters</option>
          {disasters.map((d) => <option key={d} value={d}>{d}</option>)}
        </select>
        <div className="between" style={{ marginTop: 8 }}>
          <span className="dim">Sort</span>
          <div className="seg">
            {(["severe", "buildings", "name"] as const).map((k) => (
              <button key={k} className={`btn ${sort === k ? "on" : ""}`} onClick={() => setSort(k)}>{k}</button>
            ))}
          </div>
        </div>
      </div>
      <ul className="scenes">
        {list.map((s) => {
          const tot = s.buildings || 1;
          return (
            <li key={s.pair_id} className={s.pair_id === sceneId ? "sel" : ""} onClick={() => onScene(s.pair_id)}>
              <div className="between">
                <span className="name">{s.pair_id}</span>
                <span className="dim">{s.buildings}</span>
              </div>
              <div className="bar" title="True damage mix (xBD labels)">
                {([["no-damage", s.true_none], ["minor-damage", s.true_minor], ["major-damage", s.true_major], ["destroyed", s.true_destroyed]] as const)
                  .map(([c, v]) => <span key={c} style={{ flex: v / tot, background: CLASS_COLOUR[c] }} />)}
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
