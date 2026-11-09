import { useMemo, useState } from "react";
import { Layers, Plus, Search } from "lucide-react";
import { titleCase, Upload } from "../api";
import { Badge, Button, Card, Empty, PageHeader, when } from "../ui";

/** The assessments of the user's unit tree: one row each, with where it stands. */

export function StatusBadge({ u }: { u: Upload }) {
  const s = u.status;
  if (s.state === "review") return <Badge tone="amber" dot>Check alignment</Badge>;
  if (s.state === "done") return <Badge tone="green" dot>Ready</Badge>;
  if (s.state === "failed") return <Badge tone="red" dot>Failed</Badge>;
  return <Badge tone="blue" dot>{s.state === "queued" ? "Queued" : "Assessing"}</Badge>;
}

export default function AssessmentList({ uploads, loading, onOpen, onNew }: { uploads: Upload[]; loading: boolean; onOpen: (id: string) => void; onNew: () => void }) {
  const [q, setQ] = useState("");
  const list = useMemo(() => {
    const t = q.trim().toLowerCase();
    return t ? uploads.filter((u) => `${u.name} ${u.disaster_type} ${u.id}`.toLowerCase().includes(t)) : uploads;
  }, [uploads, q]);
  const waiting = uploads.filter((u) => u.status.state === "review").length;
  return (
    <div className="page-inner">
      <PageHeader title="Assessments"
        subtitle="Before and after imagery of an area, checked for alignment and assessed for building damage. Every alert stays a draft until a person confirms it."
        actions={<Button variant="primary" icon={Plus} onClick={onNew}>New assessment</Button>} />
      {waiting > 0 && <p className="callout">{waiting === 1 ? "One assessment is" : `${waiting} assessments are`} waiting for the alignment to be checked.</p>}
      <Card flush title={loading ? "Assessments" : `${uploads.length} ${uploads.length === 1 ? "assessment" : "assessments"}`}
        actions={<label className="search"><Search size={16} aria-hidden /><input type="search" placeholder="Search by name or hazard" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search assessments" /></label>}>
        {loading ? <p className="empty-note" style={{ padding: 20 }}>Loading assessments…</p> : uploads.length === 0 ? (
          <Empty icon={Layers} title="No assessments yet">Start one with <strong>New assessment</strong>: upload the after image of an area, and the before image if you have it.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="data clickable">
              <thead><tr><th>Name</th><th>Hazard</th><th>Event date</th><th>Status</th><th className="end">Alerts</th><th>Uploaded by</th><th>Uploaded</th></tr></thead>
              <tbody>
                {list.map((u) => (
                  <tr key={u.id} onClick={() => onOpen(u.id)} tabIndex={0} onKeyDown={(e) => { if (e.key === "Enter") onOpen(u.id); }}>
                    <td><strong>{u.name}</strong></td>
                    <td>{titleCase(u.disaster_type)}</td>
                    <td>{u.event_date ?? "–"}</td>
                    <td><StatusBadge u={u} /></td>
                    <td className="end">{u.status.state === "done" ? u.status.alerts ?? 0 : "–"}</td>
                    <td>{(u as Upload & { created_by?: string }).created_by ?? "–"}</td>
                    <td>{when(u.created_utc)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {list.length === 0 && <Empty icon={Search} title="Nothing matches">Change the search.</Empty>}
          </div>
        )}
      </Card>
    </div>
  );
}
