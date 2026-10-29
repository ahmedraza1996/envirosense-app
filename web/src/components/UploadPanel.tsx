import { titleCase, Upload } from "../api";

interface Props { uploads: Upload[]; uploadId: string | null; onUpload: (id: string) => void; onNew: () => void }

function statusLine(u: Upload) {
  const s = u.status;
  if (s.state === "done") return <span className="subtle">{s.alerts ?? 0} {s.alerts === 1 ? "alert" : "alerts"}</span>;
  if (s.state === "failed") return <span className="status-failed" title={s.error}>Failed</span>;
  return <span className="status-running">{s.state === "queued" ? "Queued" : s.step ?? "Running"}…</span>;
}

export default function UploadPanel({ uploads, uploadId, onUpload, onNew }: Props) {
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
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
