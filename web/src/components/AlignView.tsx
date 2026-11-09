import { Fragment, useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, Check, CheckCircle2, Crosshair, Grid3x3, Maximize2, Minus, Plus, RotateCcw, Trash2, XCircle,
} from "lucide-react";
import { AlignChoice, Alignment, api, Upload } from "../api";
import { Badge, Button, Notice, Tone } from "../ui";

/** Step 2 of an upload: show how the before image sits on the after image, let the analyst check it (swipe, blink, overlay,
 *  side by side), correct it with tie points if needed, and confirm before the assessment runs. */

type ViewMode = "swipe" | "blink" | "overlay" | "side";
type Which = "after" | "before_placed" | "before_auto" | "before_manual";
interface View { zoom: number; x: number; y: number }

const QUALITY: Record<Alignment["quality"]["level"], { tone: Tone; label: string }> = {
  good: { tone: "green", label: "Good" }, check: { tone: "amber", label: "Check" }, poor: { tone: "red", label: "Poor" }, none: { tone: "neutral", label: "No before image" },
};
const CHOICE_LABEL: Record<AlignChoice, string> = {
  auto: "Automatic alignment", manual: "Tie points", placed: "Coordinates only", after_only: "After image only",
};
const beforeImage = (c: AlignChoice): Which => (c === "auto" ? "before_auto" : c === "manual" ? "before_manual" : "before_placed");
const pct = (v: number) => `${Math.round(v * 100)}%`;

export function Steps({ current }: { current: number }) {
  const steps = ["Upload", "Check alignment", "Assess", "Review alerts"];
  return (
    <ol className="steps" aria-label="Progress">
      {steps.map((s, i) => (
        <li key={s} className={i < current ? "done" : i === current ? "current" : ""} aria-current={i === current ? "step" : undefined}>
          <span className="step-dot">{i < current ? <Check size={12} aria-hidden /> : i + 1}</span>{s}
        </li>
      ))}
    </ol>
  );
}

export default function AlignView({ upload, onConfirmed }: { upload: Upload; onConfirmed: (u: Upload) => void }) {
  const [al, setAl] = useState<Alignment | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [mode, setMode] = useState<ViewMode>("swipe");
  const [swipe, setSwipe] = useState(50);
  const [opacity, setOpacity] = useState(0.5);
  const [blinkBefore, setBlinkBefore] = useState(false);
  const [grid, setGrid] = useState(true);
  const [view, setView] = useState<View>({ zoom: 1, x: 0, y: 0 });
  const [hover, setHover] = useState<[number, number] | null>(null);
  const [placing, setPlacing] = useState(false);
  const [pairs, setPairs] = useState<number[][]>([]);
  const [pending, setPending] = useState<[number, number] | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);
  const drag = useRef<{ x: number; y: number; vx: number; vy: number; moved: boolean } | null>(null);

  useEffect(() => {
    api.alignment(upload.id).then((a) => { setAl(a); setPairs(a.manual?.pairs ?? []); }).catch((e) => setError(String(e)));
  }, [upload.id]);

  // blink: alternate before and after
  useEffect(() => {
    if (mode !== "blink") return;
    const t = setInterval(() => setBlinkBefore((b) => !b), 700);
    return () => clearInterval(t);
  }, [mode]);

  // wheel zoom around the cursor (a non-passive listener so the page does not scroll)
  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      const pane = (e.target as Element).closest(".align-stage");
      if (!pane) return;
      e.preventDefault();
      const r = pane.getBoundingClientRect();
      const cx = e.clientX - r.left, cy = e.clientY - r.top;
      setView((v) => {
        const zoom = Math.min(8, Math.max(1, v.zoom * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
        const k = zoom / v.zoom;
        return clampView({ zoom, x: cx - (cx - v.x) * k, y: cy - (cy - v.y) * k }, r.width, r.height);
      });
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  });

  const clampView = (v: View, w: number, h: number): View =>
    ({ zoom: v.zoom, x: Math.min(0, Math.max(w - w * v.zoom, v.x)), y: Math.min(0, Math.max(h - h * v.zoom, v.y)) });

  const zoomBy = (f: number) => {
    const r = stage.current?.getBoundingClientRect();
    if (!r) return;
    setView((v) => {
      const zoom = Math.min(8, Math.max(1, v.zoom * f)), k = zoom / v.zoom;
      return clampView({ zoom, x: r.width / 2 - (r.width / 2 - v.x) * k, y: r.height / 2 - (r.height / 2 - v.y) * k }, r.width, r.height);
    });
  };

  // pointer position -> preview pixels (the same in both panes of the side-by-side view)
  const toImage = useCallback((e: React.PointerEvent, pane: HTMLElement): [number, number] | null => {
    if (!al) return null;
    const r = pane.getBoundingClientRect();
    const x = (e.clientX - r.left - view.x) / view.zoom / r.width * al.preview.width;
    const y = (e.clientY - r.top - view.y) / view.zoom / r.height * al.preview.height;
    return x < 0 || y < 0 || x > al.preview.width || y > al.preview.height ? null : [x, y];
  }, [al, view]);

  const onDown = (e: React.PointerEvent) => {
    drag.current = { x: e.clientX, y: e.clientY, vx: view.x, vy: view.y, moved: false };
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
  };
  const onMove = (e: React.PointerEvent) => {
    setHover(toImage(e, e.currentTarget as HTMLElement));
    const d = drag.current;
    if (!d) return;
    const dx = e.clientX - d.x, dy = e.clientY - d.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) d.moved = true;
    if (mode === "swipe" && !placing && !d.moved) return;
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    if (d.moved) setView((v) => clampView({ ...v, x: d.vx + dx, y: d.vy + dy }, r.width, r.height));
  };
  const onUp = (e: React.PointerEvent, pane: "before" | "after" | "single") => {
    const d = drag.current;
    drag.current = null;
    if (!d || d.moved) return;
    const p = toImage(e, e.currentTarget as HTMLElement);
    if (placing && p) {
      if (pane === "before") setPending(p);
      else if (pane === "after" && pending) { setPairs((xs) => [...xs, [pending[0], pending[1], p[0], p[1]]]); setPending(null); }
      return;
    }
    if (mode === "swipe" && pane === "single") {
      const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
      setSwipe(Math.min(100, Math.max(0, ((e.clientX - r.left) / r.width) * 100)));
    }
  };

  const act = async (fn: () => Promise<Alignment>) => {
    setBusy(true); setError(null);
    try { setAl(await fn()); } catch (e) { setError(String(e).replace(/^Error: /, "")); } finally { setBusy(false); }
  };
  const choose = (c: AlignChoice) => { if (al && c !== al.choice) void act(() => api.chooseAlignment(upload.id, c)); };
  const fit = () => void act(async () => {
    const a = await api.alignManually(upload.id, pairs);
    setPlacing(false); setMode("swipe");
    return a;
  });
  const confirm = async () => {
    setBusy(true); setError(null);
    try { onConfirmed(await api.confirmAlignment(upload.id)); } catch (e) { setError(String(e).replace(/^Error: /, "")); setBusy(false); }
  };
  const startPlacing = () => { setPlacing(true); setMode("side"); setPending(null); };

  if (error && !al) return <div className="align-page"><Notice tone="error">{error}</Notice></div>;
  if (!al) return <div className="align-page"><p className="empty-note">Loading the alignment…</p></div>;

  const v = al.version;
  const shownBefore: Which = placing ? "before_placed" : beforeImage(al.choice);
  const src = (w: Which) => api.previewUrl(upload.id, w, v);
  const world = { transform: `translate(${view.x}px, ${view.y}px) scale(${view.zoom})` };
  const q = QUALITY[al.quality.level];
  const stats = al.choice === "manual" && al.manual
    ? [["Method", `${al.manual.pairs.length} pairs of tie points`], ["Residual", `${al.manual.rms_m.toFixed(1)} m`],
       ["Correction", `${al.manual.shift_m.toFixed(1)} m, ${al.manual.rotation_deg.toFixed(2)}°, zoom ${((al.manual.scale - 1) * 100).toFixed(1)}%`],
       ["Overlap", pct(al.manual.coverage)]]
    : [["Method", al.auto.method ?? "none"], ["Matching features", al.auto.inliers != null ? `${al.auto.inliers} of ${al.auto.matches}` : "–"],
       ["Residual", al.auto.rms_px != null ? `${(al.auto.rms_px * al.pixel_size_m).toFixed(1)} m` : "–"],
       ["Correction", al.auto.corrected ? `${(al.auto.shift_m ?? 0).toFixed(1)} m, ${(al.auto.rotation_deg ?? 0).toFixed(2)}°, zoom ${(((al.auto.scale ?? 1) - 1) * 100).toFixed(1)}%` : "none needed"],
       ["Overlap", pct(al.auto.coverage)]];

  const marks = (side: "before" | "after") => (
    <>
      {pairs.map((p, i) => (
        <span key={i} className={`tie ${side}`} style={{ left: `${((side === "before" ? p[0] : p[2]) / al.preview.width) * 100}%`, top: `${((side === "before" ? p[1] : p[3]) / al.preview.height) * 100}%`, transform: `translate(-50%, -50%) scale(${1 / view.zoom})` }}>{i + 1}</span>
      ))}
      {side === "before" && pending && (
        <span className="tie before pending" style={{ left: `${(pending[0] / al.preview.width) * 100}%`, top: `${(pending[1] / al.preview.height) * 100}%`, transform: `translate(-50%, -50%) scale(${1 / view.zoom})` }}>{pairs.length + 1}</span>
      )}
      {!placing && hover && mode === "side" && (
        <span className="cursor-mark" style={{ left: `${(hover[0] / al.preview.width) * 100}%`, top: `${(hover[1] / al.preview.height) * 100}%`, transform: `translate(-50%, -50%) scale(${1 / view.zoom})` }} />
      )}
    </>
  );
  const gridLayer = grid && <div className="align-grid" style={{ backgroundSize: `${100 / 8}% ${100 / 8}%` }} />;
  const aspect = { aspectRatio: `${al.preview.width} / ${al.preview.height}`, maxWidth: `calc((100vh - 290px) * ${al.preview.width / al.preview.height})` };

  return (
    <div className="align-page">
      <div className="align-head">
        <div>
          <h1>Check the alignment</h1>
          <p>{upload.name}: the before image has been placed on the after image. Check that buildings and roads line up before the damage assessment runs.</p>
        </div>
        <Steps current={1} />
      </div>

      <div className="align-body">
        <section className="card align-viewer">
          <div className="align-toolbar">
            <div className="segmented" role="group" aria-label="Comparison">
              {(["swipe", "blink", "overlay", "side"] as ViewMode[]).map((m) => (
                <button key={m} aria-pressed={mode === m} disabled={placing && m !== "side"} onClick={() => setMode(m)}>
                  {{ swipe: "Swipe", blink: "Blink", overlay: "Overlay", side: "Side by side" }[m]}
                </button>
              ))}
            </div>
            {mode === "overlay" && (
              <label className="field-inline">Before <input type="range" min={0} max={1} step={0.05} value={opacity} onChange={(e) => setOpacity(+e.target.value)} aria-label="Before image opacity" /></label>
            )}
            <span className="spacer" />
            <button className={`icon-btn ${grid ? "on" : ""}`} aria-pressed={grid} title="Grid" aria-label="Grid" onClick={() => setGrid((g) => !g)}><Grid3x3 size={17} /></button>
            <button className="icon-btn" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.5)}><Minus size={17} /></button>
            <span className="zoom-level">{Math.round(view.zoom * 100)}%</span>
            <button className="icon-btn" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(1.5)}><Plus size={17} /></button>
            <button className="icon-btn" title="Fit" aria-label="Fit" onClick={() => setView({ zoom: 1, x: 0, y: 0 })}><Maximize2 size={17} /></button>
          </div>

          <div ref={canvas}>
          {mode === "side" ? (
            <div className="align-side">
              {(["before", "after"] as const).map((side) => (
                <figure key={side}>
                  <figcaption>{side === "before" ? `Before · ${placing ? "as placed by coordinates" : CHOICE_LABEL[al.choice].toLowerCase()}` : "After"}</figcaption>
                  <div className={`align-stage ${placing ? "placing" : ""}`} style={aspect} ref={side === "after" ? stage : undefined}
                    onPointerDown={onDown} onPointerMove={onMove} onPointerUp={(e) => onUp(e, side)} onPointerLeave={() => setHover(null)}>
                    <div className="align-world" style={world}>
                      <img src={src(side === "before" ? shownBefore : "after")} alt={side} draggable={false} />
                      {gridLayer}
                      {marks(side)}
                    </div>
                  </div>
                </figure>
              ))}
            </div>
          ) : (
            <div className="align-stage" style={aspect} ref={stage} onPointerDown={onDown} onPointerMove={onMove} onPointerUp={(e) => onUp(e, "single")}
              onPointerLeave={() => setHover(null)}>
              <div className="align-layer"><div className="align-world" style={world}><img src={src("after")} alt="After" draggable={false} /></div></div>
              <div className="align-layer" style={{
                clipPath: mode === "swipe" ? `inset(0 ${100 - swipe}% 0 0)` : undefined,
                opacity: mode === "overlay" ? opacity : mode === "blink" ? (blinkBefore ? 1 : 0) : 1,
              }}>
                <div className="align-world" style={world}><img src={src(shownBefore)} alt="Before" draggable={false} /></div>
              </div>
              <div className="align-layer passive"><div className="align-world" style={world}>{gridLayer}</div></div>
              {mode === "swipe" && <div className="swipe-handle" style={{ left: `${swipe}%` }}><span>Before</span><span>After</span></div>}
              {mode === "blink" && <span className="blink-label">{blinkBefore ? "Before" : "After"}</span>}
            </div>
          )}
          </div>
          <p className="align-hint">
            {placing
              ? pending ? `Now click the same point in the after image (pair ${pairs.length + 1}).` : "Click a corner, road junction or roof edge in the before image, then the same point in the after image."
              : mode === "swipe" ? "Click or drag across the image to move the divide; scroll to zoom, drag to pan. Edges should continue straight across the divide."
                : mode === "blink" ? "Buildings that stay still are aligned; anything that jumps is misplaced (or changed by the disaster)."
                  : "Scroll to zoom, drag to pan; both images move together."}
          </p>
        </section>

        <aside className="align-panel">
          <section className="card">
            <div className="card-head">
              <h2>Alignment</h2>
              <Badge tone={q.tone} dot>{q.label}</Badge>
            </div>
            <div className="card-body">
              <p className="lead">{al.choice === "manual" && al.manual ? `Aligned by hand from ${al.manual.pairs.length} pairs of points.` : al.quality.text}</p>
              <dl className="facts">{stats.map(([k, val]) => <Fragment key={k}><dt>{k}</dt><dd>{val}</dd></Fragment>)}</dl>
            </div>
          </section>

          <section className="card">
            <div className="card-head"><h2>Input checks</h2></div>
            <ul className="checks">
              {al.checks.map((c) => (
                <li key={c.name} className={c.level}>
                  {c.level === "ok" ? <CheckCircle2 size={16} aria-hidden /> : c.level === "warn" ? <AlertTriangle size={16} aria-hidden /> : <XCircle size={16} aria-hidden />}
                  <div><strong>{c.name}</strong><span>{c.text}</span></div>
                </li>
              ))}
            </ul>
          </section>

          <section className="card">
            <div className="card-head"><h2>Before image to use</h2></div>
            <div className="card-body choice-list" role="radiogroup" aria-label="Before image to use">
              {(["auto", "manual", "placed", "after_only"] as AlignChoice[]).filter((c) => c !== "manual" || al.manual).map((c) => (
                <label key={c} className={al.choice === c ? "on" : ""}>
                  <input type="radio" name="choice" checked={al.choice === c} disabled={busy || placing} onChange={() => choose(c)} />
                  <span><strong>{CHOICE_LABEL[c]}{c === "auto" && al.quality.level === "good" ? " (recommended)" : ""}</strong>
                    <small>{{ auto: "Coordinates, then matched features.", manual: "From the points you placed.", placed: "As the coordinates say, no correction.", after_only: "Ignore the before image; less reliable." }[c]}</small></span>
                </label>
              ))}
            </div>
            <div className="card-body tie-tools">
              {!placing ? (
                <Button icon={Crosshair} onClick={startPlacing} disabled={busy}>Correct with tie points</Button>
              ) : (
                <>
                  <ol className="tie-list">
                    {pairs.map((_, i) => (
                      <li key={i}><span className="tie-no">{i + 1}</span>
                        {al.manual?.residuals_m[i] != null && al.manual.pairs.length === pairs.length ? `off by ${al.manual.residuals_m[i].toFixed(1)} m` : "placed"}
                        <button className="icon-btn" aria-label={`Remove pair ${i + 1}`} onClick={() => setPairs((xs) => xs.filter((_, j) => j !== i))}><Trash2 size={15} /></button>
                      </li>
                    ))}
                  </ol>
                  <div className="row-actions">
                    <Button variant="primary" onClick={fit} disabled={busy || pairs.length < 2}>Align from {pairs.length} pairs</Button>
                    <Button icon={RotateCcw} variant="ghost" onClick={() => { setPlacing(false); setPending(null); setPairs(al.manual?.pairs ?? []); }}>Cancel</Button>
                  </div>
                  <small className="subtle">Two pairs fix shift, rotation and zoom; three or more spread over the image are better.</small>
                </>
              )}
            </div>
          </section>

          {error && <Notice tone="error">{error}</Notice>}
          <div className="confirm-bar">
            <Button variant="primary" icon={Check} onClick={confirm} disabled={busy || placing}>Looks right: run the assessment</Button>
            <small className="subtle">Your check is recorded with your name. Using: {CHOICE_LABEL[al.choice].toLowerCase()}.</small>
          </div>
        </aside>
      </div>
    </div>
  );
}
