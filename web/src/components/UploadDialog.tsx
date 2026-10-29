import { FormEvent, useEffect, useRef, useState } from "react";
import { api, DISASTER_TYPES, ModelInfo, titleCase, Upload } from "../api";

interface Props { models: ModelInfo[]; onClose: () => void; onCreated: (u: Upload) => void }

const isGeoTiff = (f: File | null) => !!f && /\.tiff?$/i.test(f.name);
const CORNERS = ["west", "south", "east", "north"] as const;

export default function UploadDialog({ models, onClose, onCreated }: Props) {
  const unets = models.filter((m) => m.kind === "unet");
  const [after, setAfter] = useState<File | null>(null);
  const [before, setBefore] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [type, setType] = useState("other");
  const [date, setDate] = useState("");
  const [model, setModel] = useState(unets.find((m) => m.id === "unet_early")?.id ?? unets[0]?.id ?? "");
  const [corners, setCorners] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const needCorners = !!after && !isGeoTiff(after);

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
    if (needCorners) CORNERS.forEach((c) => form.append(c, corners[c] ?? ""));
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
          <p className="meta">The after image is assessed for damage. Its location is used to find a before image, which
            shows where buildings stood.</p>
        </header>

        <div className="form-grid">
          <label className="field">
            <span>After image</span>
            <input type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" required onChange={(e) => setAfter(e.target.files?.[0] ?? null)} />
            <small>GeoTIFF with its georeferencing, or PNG/JPEG with corner coordinates. Up to about 2 × 2 km.</small>
          </label>

          {needCorners && (
            <fieldset className="field corners">
              <legend>Corner coordinates of the after image (degrees, north-up)</legend>
              {CORNERS.map((c) => (
                <label key={c}>
                  <span>{titleCase(c)}</span>
                  <input type="number" step="any" required value={corners[c] ?? ""}
                    placeholder={c === "west" || c === "east" ? "longitude" : "latitude"}
                    onChange={(e) => setCorners({ ...corners, [c]: e.target.value })} />
                </label>
              ))}
            </fieldset>
          )}

          <label className="field">
            <span>Before image <em>optional</em></span>
            <input type="file" accept=".tif,.tiff,.png,.jpg,.jpeg" onChange={(e) => setBefore(e.target.files?.[0] ?? null)} />
            <small>Leave empty to search the archive. A plain image is taken to cover the same corners as the after image.</small>
          </label>

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
                {unets.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </select>
            </label>
          </div>
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}
        <footer>
          <button type="button" className="button" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="button primary" disabled={busy || !after || !model}>
            {busy ? "Uploading…" : "Start assessment"}
          </button>
        </footer>
      </form>
    </dialog>
  );
}
