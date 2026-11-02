import { useState } from "react";
import { titleCase, Upload } from "../api";

interface Props {
  uploads: Upload[]; uploadId: string | null; onUpload: (id: string) => void; onNew: () => void;
  onRename: (id: string, name: string) => Promise<void>; onDelete: (id: string) => Promise<void>;
}

function statusLine(u: Upload) {
  const s = u.status;
  if (s.state === "done") return <span className="subtle">{s.alerts ?? 0} {s.alerts === 1 ? "alert" : "alerts"}</span>;
  if (s.state === "failed") return <span className="status-failed" title={s.error}>Failed</span>;
  return <span className="status-running">{s.state === "queued" ? "Queued" : s.step ?? "Running"}…</span>;
}

function Actions({ u, onRename, onDelete }: { u: Upload; onRename: Props["onRename"]; onDelete: Props["onDelete"] }) {
  const [mode, setMode] = useState<"idle" | "rename" | "delete">("idle");
  const [name, setName] = useState(u.name);
  const [error, setError] = useState<string | null>(null);
  const busy = u.status.state === "queued" || u.status.state === "running";
  const run = async (fn: () => Promise<void>) => {
    setError(null);
    try { await fn(); setMode("idle"); } catch (e) { setError(String(e).replace(/^Error: /, "")); }
  };
  if (mode === "rename") {
    return (
      <form className="item-actions" onClick={(e) => e.stopPropagation()} onSubmit={(e) => { e.preventDefault(); void run(() => onRename(u.id, name)); }}>
        <input className="rename-input" value={name} maxLength={80} autoFocus aria-label="Upload name" onChange={(e) => setName(e.target.value)} />
        <button className="link" type="submit">Save</button>
        <button className="link" type="button" onClick={() => setMode("idle")}>Cancel</button>
        {error && <span className="upload-error">{error}</span>}
      </form>
    );
  }
  if (mode === "delete") {
    return (
      <div className="item-actions" onClick={(e) => e.stopPropagation()}>
        <span>Delete this upload and its results?</span>
        <button className="link danger" onClick={() => void run(() => onDelete(u.id))}>Delete</button>
        <button className="link" onClick={() => setMode("idle")}>Keep</button>
        {error && <span className="upload-error">{error}</span>}
      </div>
    );
  }
  return (
    <div className="item-actions" onClick={(e) => e.stopPropagation()}>
      <button className="link" onClick={() => { setName(u.name); setMode("rename"); }}>Rename</button>
      <button className="link danger" disabled={busy} title={busy ? "Wait until processing has finished" : undefined} onClick={() => setMode("delete")}>Delete</button>
    </div>
  );
}

export default function UploadPanel({ uploads, uploadId, onUpload, onNew, onRename, onDelete }: Props) {
  return (
    <>
      <div className="sidebar-head">
        <button className="button primary" onClick={onNew}>Upload imagery</button>
        <span className="count">
          After image with location; the before image is found in the archive or uploaded with it.
        </span>
      </div>
      {uploads.length === 0 ? (
        <p className="empty-note sidebar-empty">No uploads yet.</p>
      ) : (
        <ul className="scene-list" role="listbox">
          {uploads.map((u) => (
            <li key={u.id} role="option" aria-selected={u.id === uploadId} onClick={() => onUpload(u.id)}>
              <div className="scene-title">
                <strong>{u.name}</strong>
                {statusLine(u)}
              </div>
              <span className="scene-id">{titleCase(u.disaster_type)} · {u.id}</span>
              {u.status.state === "failed" && <span className="upload-error">{u.status.error}</span>}
              {u.id === uploadId && <Actions key={u.id + u.name} u={u} onRename={onRename} onDelete={onDelete} />}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
