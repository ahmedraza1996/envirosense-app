import { useMemo, useState } from "react";
import { CLASS_COLOUR, Scene, tileNo, titleCase } from "../api";

interface Props { scenes: Scene[]; disasters: string[]; sceneId: string | null; onScene: (id: string) => void }

const SORTS = { severe: "By damage", buildings: "By size", tile: "By tile" } as const;
type Sort = keyof typeof SORTS;

export default function ScenePanel({ scenes, disasters, sceneId, onScene }: Props) {
  const [query, setQuery] = useState("");
  const [disaster, setDisaster] = useState("");
  const [sort, setSort] = useState<Sort>("severe");

  const list = useMemo(() => {
    const q = query.trim().toLowerCase();
    const s = scenes.filter((x) => (!disaster || x.disaster === disaster) && (!q || x.pair_id.toLowerCase().includes(q)));
    const key: Record<Sort, (x: Scene) => number> = { severe: (x) => -x.severe_true, buildings: (x) => -x.buildings, tile: () => 0 };
    return [...s].sort((a, b) => key[sort](a) - key[sort](b) || a.pair_id.localeCompare(b.pair_id));
  }, [scenes, query, disaster, sort]);

  return (
    <nav className="sidebar" aria-label="Scenes">
      <div className="sidebar-head">
        <input type="search" placeholder="Search tiles" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Search tiles" />
        <div className="row">
          <select value={disaster} onChange={(e) => setDisaster(e.target.value)} aria-label="Disaster">
            <option value="">All disasters</option>
            {disasters.map((d) => <option key={d} value={d}>{titleCase(d)}</option>)}
          </select>
          <select value={sort} onChange={(e) => setSort(e.target.value as Sort)} aria-label="Sort">
            {Object.entries(SORTS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
        </div>
        <span className="count">{list.length} of {scenes.length} tiles</span>
      </div>
      <ul className="scene-list" role="listbox">
        {list.map((s) => (
          <li key={s.pair_id} role="option" aria-selected={s.pair_id === sceneId} onClick={() => onScene(s.pair_id)}>
            <div className="scene-title">
              <strong>{titleCase(s.disaster)}</strong>
              <span className="subtle">{s.buildings}</span>
            </div>
            <span className="scene-id">Tile {tileNo(s.pair_id)}</span>
            <div className="mix" title="Damage mix in the xBD labels">
              <span style={{ flex: s.true_none, background: CLASS_COLOUR["no-damage"] }} />
              <span style={{ flex: s.true_minor, background: CLASS_COLOUR["minor-damage"] }} />
              <span style={{ flex: s.true_major, background: CLASS_COLOUR["major-damage"] }} />
              <span style={{ flex: s.true_destroyed, background: CLASS_COLOUR.destroyed }} />
            </div>
          </li>
        ))}
      </ul>
    </nav>
  );
}
