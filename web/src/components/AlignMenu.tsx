import { useEffect, useRef, useState } from "react";
import { api, Assessment, GeoSuggestion } from "../api";

// Moves the image, its outlines and its alerts together on the street map (a translation in metres, stored with the assessment).
// The outlines always fit the image; this only fixes where the georeference puts the image against the street map.

const STEPS = [1, 5, 20];
const dir = (v: number, pos: string, neg: string) => (Math.abs(v) < 0.05 ? "0 m" : `${Math.abs(v).toFixed(1)} m ${v > 0 ? pos : neg}`);

export default function AlignMenu({ assessment, onAssessment }: { assessment: Assessment; onAssessment: (a: Assessment) => void }) {
  const aid = assessment.id;
  const saved = assessment.scene.geo_offset_m ?? { east: 0, north: 0, method: null };
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState(5);
  const [target, setTarget] = useState({ east: saved.east, north: saved.north });
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [suggestion, setSuggestion] = useState<GeoSuggestion | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  useEffect(() => { setTarget({ east: saved.east, north: saved.north }); setSuggestion(null); setError(null); }, [aid, saved.east, saved.north]);
  useEffect(() => {
    const close = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", close);
    return () => { document.removeEventListener("mousedown", close); clearTimeout(timer.current); };
  }, []);

  const commit = async (east: number, north: number, method: string, note?: string) => {
    setError(null);
    try {
      await api.setGeoOffset(aid, east, north, method, note);
      onAssessment(await api.assessment(aid));
    } catch (e) { setError((e as Error).message); }
  };
  const nudge = (de: number, dn: number) => {
    const next = { east: Math.round((target.east + de) * 10) / 10, north: Math.round((target.north + dn) * 10) / 10 };
    setTarget(next);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => { void commit(next.east, next.north, "manual"); }, 350);
  };
  const measure = async () => {
    setBusy("Asking OpenStreetMap… up to two minutes"); setError(null); setSuggestion(null);
    try { setSuggestion(await api.measureGeoOffset(aid)); } catch (e) { setError((e as Error).message); }
    setBusy(null);
  };
  const apply = async (s: GeoSuggestion) => {
    setBusy("Applying…");
    await commit(s.east_m, s.north_m, "OpenStreetMap buildings", `${s.buildings} buildings, sharpness ${s.sharpness}`);
    setBusy(null); setSuggestion(null);
  };
  const moved = Math.abs(target.east) > 0.04 || Math.abs(target.north) > 0.04;

  return (
    <div className="layers" ref={ref}>
      <button className="button panel-float" aria-expanded={open} onClick={() => setOpen(!open)}>
        Align{moved ? ` · ${Math.hypot(target.east, target.north).toFixed(0)} m` : ""}
      </button>
      {open && (
        <div className="layers-menu align-menu panel-float">
          <p className="subtle">Image, outlines and alerts move together against the street map. The outlines already fit the image.</p>
          <div className="align-pad" role="group" aria-label="Move on the map">
            <button className="button" style={{ gridArea: "n" }} onClick={() => nudge(0, step)} aria-label="Move north">▲</button>
            <button className="button" style={{ gridArea: "w" }} onClick={() => nudge(-step, 0)} aria-label="Move west">◀</button>
            <span style={{ gridArea: "c" }} className="subtle">{step} m</span>
            <button className="button" style={{ gridArea: "e" }} onClick={() => nudge(step, 0)} aria-label="Move east">▶</button>
            <button className="button" style={{ gridArea: "s" }} onClick={() => nudge(0, -step)} aria-label="Move south">▼</button>
          </div>
          <div className="segmented" role="group" aria-label="Step size">
            {STEPS.map((s) => <button key={s} aria-pressed={step === s} onClick={() => setStep(s)}>{s} m</button>)}
          </div>
          <p>Now: {dir(target.east, "east", "west")}, {dir(target.north, "north", "south")}
            {saved.method && saved.method !== "manual" ? <span className="subtle"> ({saved.method})</span> : null}</p>
          <button className="button" onClick={measure} disabled={busy !== null}>Measure from OpenStreetMap</button>
          {suggestion && (
            <div className="align-suggestion">
              <p>Suggested: {dir(suggestion.east_m, "east", "west")}, {dir(suggestion.north_m, "north", "south")}
                <span className={suggestion.clear ? "" : "subtle"}> · {suggestion.clear ? "clear match" : "weak match"}</span></p>
              <p className="subtle">{suggestion.buildings} buildings. {suggestion.note}</p>
              <button className="button primary" onClick={() => apply(suggestion)} disabled={busy !== null}>Apply</button>
            </div>
          )}
          {moved && <button className="button" onClick={() => { setTarget({ east: 0, north: 0 }); void commit(0, 0, "manual"); }}>Reset to file position</button>}
          {busy && <p className="subtle">{busy}</p>}
          {error && <p className="error-text">{error}</p>}
        </div>
      )}
    </div>
  );
}
