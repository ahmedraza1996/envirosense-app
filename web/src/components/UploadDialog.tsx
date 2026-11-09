import { FormEvent, useEffect, useRef, useState } from "react";
import { api, bestUnet, DISASTER_TYPES, ModelInfo, titleCase, Upload } from "../api";

interface Props { models: ModelInfo[]; onClose: () => void; onCreated: (u: Upload) => void }

const isGeoTiff = (f: File | null) => !!f && /\.tiff?$/i.test(f.name);
const CORNERS = ["west", "south", "east", "north"] as const;
type Corners = Record<string, string>;

function CornerInputs({ legend, value, onChange, action }: { legend: string; value: Corners; onChange: (v: Corners) => void; action?: React.ReactNode }) {
  return (
    <fieldset className="field corners">
      <legend>{legend}</legend>
      {CORNERS.map((c) => (
        <label key={c}>
          <span>{titleCase(c)}</span>
          <input type="number" step="any" required value={value[c] ?? ""}
            placeholder={c === "west" || c === "east" ? "longitude" : "latitude"}
            onChange={(e) => onChange({ ...value, [c]: e.target.value })} />
        </label>
      ))}
      {action}
    </fieldset>
  );
}

const asCorners = (o: Record<string, number> | undefined): Corners | null =>
  o && CORNERS.every((c) => typeof o[c] === "number") ? Object.fromEntries(CORNERS.map((c) => [c, String(o[c])])) : null;

export default function UploadDialog({ models, onClose, onCreated }: Props) {
  const unets = models.filter((m) => m.kind === "unet");
  const [after, setAfter] = useState<File | null>(null);
  const [before, setBefore] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("other");
  const [policy, setPolicy] = useState("");
  useEffect(() => { api.policy().then((p) => setPolicy(p.notice)).catch(() => undefined); }, []);
  const [date, setDate] = useState("");
  const [model, setModel] = useState(bestUnet(models)?.id ?? "");
  const [corners, setCorners] = useState<Corners>({});
  const [beforeCorners, setBeforeCorners] = useState<Corners>({});
  const [loaded, setLoaded] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const needCorners = !!after && !isGeoTiff(after);
  const needBeforeCorners = !!before && !isGeoTiff(before);

  // metadata.json (from the demo set, or written by hand): fills the form
  const loadMetadata = async (f: File | null) => {
    if (!f) return;
    try {
      const m = JSON.parse(await f.text());
      if (m.name) setName(String(m.name));
      if (DISASTER_TYPES.includes(m.disaster_type)) setType(m.disaster_type);
      if (m.event_date) setDate(String(m.event_date).slice(0, 10));
      const a = asCorners(m.after_corners), b = asCorners(m.before_corners);
      if (a) setCorners(a);
      if (b) setBeforeCorners(b);
      setLoaded(`${f.name}: ${[m.name && "name", m.disaster_type && "type", m.event_date && "date", a && "after corners", b && "before corners"].filter(Boolean).join(", ")}`);
      setError(null);
    } catch {
      setLoaded(null);
      setError(`${f.name} is not valid JSON`);
    }
  };

  useEffect(() => { dialog.current?.showModal(); }, []);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!after) return;
    const form = new FormData();
    form.append("after", after);
    if (before) form.append("before", before);
    form.append("name", name.trim() || after.name.replace(/\.[^.]+$/, ""));
    form.append("disaster_type", type);
    form.append("event_date", date);
    form.append("model_id", model);
    form.append("review_alignment", "true");
    if (needCorners) CORNERS.forEach((c) => form.append(c, corners[c] ?? ""));
    if (needBeforeCorners) CORNERS.forEach((c) => form.append(`before_${c}`, beforeCorners[c] ?? ""));
    setBusy(true);
    setError(null);
    try {
      onCreated(await api.upload(form));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <dialog ref={dialog} className="dialog" onClose={onClose} onCancel={onClose}>
      <form onSubmit={submit}>
        <header>
          <h1>Upload imagery</h1>
          <ol className="steps compact" aria-label="Progress">
            <li className="current"><span className="step-dot">1</span>Upload</li><li><span className="step-dot">2</span>Check alignment</li>
            <li><span className="step-dot">3</span>Assess</li><li><span className="step-dot">4</span>Review alerts</li>
          </ol>
          <p className="meta">The after image is assessed for damage. The before image shows where buildings stood: upload it with the after image,
            or leave it out and one is looked for in the archive. Next you will see the two images on top of each other and confirm that they line up.</p>
          {policy && <p className="meta note">{policy}</p>}
        </header>

        <div className="form-grid">
          <label className="field">
            <span>Metadata file <em>optional</em></span>
            <input type="file" accept=".json,application/json" onChange={(e) => loadMetadata(e.target.files?.[0] ?? null)} />
            <small>{loaded ? `Filled from ${loaded}` : "A metadata.json fills in the name, type, date and corner coordinates below."}</small>
          </label>

          <label className="field">
            <span>After image</span>
            <input type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" required onChange={(e) => setAfter(e.target.files?.[0] ?? null)} />
            <small>GeoTIFF with its georeferencing, or PNG/JPEG with corner coordinates. Up to about 2 × 2 km.</small>
          </label>

          {needCorners && <CornerInputs legend="Corner coordinates of the after image (degrees, north-up)" value={corners} onChange={setCorners} />}

          <label className="field">
            <span>Before image <em>optional</em></span>
            <input type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" onChange={(e) => setBefore(e.target.files?.[0] ?? null)} />
            <small>Leave empty to search the archive for one.</small>
          </label>

          {needBeforeCorners && (
            <CornerInputs legend="Corner coordinates of the before image (degrees, north-up)" value={beforeCorners} onChange={setBeforeCorners}
              action={needCorners ? <button type="button" className="link copy-corners" onClick={() => setBeforeCorners(corners)}>Same as after image</button> : undefined} />
          )}

          <div className="row-2">
            <label className="field">
              <span>Name</span>
              <input type="text" value={name} placeholder={after?.name.replace(/\.[^.]+$/, "") ?? "e.g. Lahaina, west side"}
                onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>Disaster type</span>
              <select value={type} onChange={(e) => setType(e.target.value)}>
                {DISASTER_TYPES.map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}
              </select>
            </label>
          </div>

          <div className="row-2">
            <label className="field">
              <span>Event date <em>optional</em></span>
              <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <small>Before images must be captured earlier.</small>
            </label>
            <label className="field">
              <span>Model</span>
              <select value={model} onChange={(e) => setModel(e.target.value)}>
                {unets.map((m) => <option key={m.id} value={m.id}>{m.label}{m.test_score != null ? ` · test ${m.test_score.toFixed(2)}` : ""}</option>)}
              </select>
            </label>
          </div>
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}
        <footer>
          <button type="button" className="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !after || !model}>
            {busy ? "Uploading…" : "Upload and check alignment"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
