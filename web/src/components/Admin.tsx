import { FormEvent, useCallback, useEffect, useState } from "react";
import { accounts, ApprovedModel, AuditEntry, PermissionCatalogue, Role, RoleInfo, UnitInfo, User } from "../api";

const msg = (e: unknown) => String(e).replace(/^Error: /, "");
function useLoad<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const reload = useCallback(() => { fn().then(setData).catch((e) => setError(msg(e))); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(reload, [reload]);
  return { data, error, reload };
}

function Users({ me }: { me: User }) {
  const users = useLoad(accounts.users), units = useLoad(accounts.units), roles = useLoad(accounts.roles);
  const ROLES = (roles.data ?? []).map((r) => ({ id: r.key, label: r.label, help: r.description }));
  const [form, setForm] = useState({ username: "", name: "", role: "analyst" as Role, unit: "" });
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState<{ who: string; pw: string } | null>(null);
  const unitList = units.data ?? [];
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn(); users.reload(); units.reload(); } catch (e) { setError(msg(e)); } };
  const add = (e: FormEvent) => {
    e.preventDefault();
    void run(async () => {
      const u = await accounts.addUser({ ...form, unit: form.unit || me.unit });
      setShown({ who: u.username, pw: u.temporary_password ?? "" });
      setForm({ username: "", name: "", role: form.role, unit: form.unit });
    });
  };
  return (
    <>
      <h2>Add a user</h2>
      <form className="admin-form" onSubmit={add}>
        <label className="field-block"><span>Username</span><input type="text" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></label>
        <label className="field-block"><span>Full name</span><input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field-block"><span>Role</span>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}</select></label>
        <label className="field-block"><span>Unit</span>
          <select value={form.unit || me.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>{unitList.map((u) => <option key={u.id} value={u.id}>{u.path}</option>)}</select></label>
        <button className="button primary" disabled={!form.username || !form.name}>Create user</button>
      </form>
      <p className="meta">{ROLES.find((r) => r.id === form.role)?.help} A temporary password is shown once; the user must change it at first sign-in.</p>
      {shown && <p className="notice">Temporary password for <strong>{shown.who}</strong>: <code>{shown.pw}</code>. Pass it on privately; it is not shown again.</p>}
      {error && <p className="meta error-text" role="alert">{error}</p>}
      <h2>Users ({users.data?.length ?? 0})</h2>
      <table>
        <thead><tr><th>User</th><th>Role</th><th>Unit</th><th>Last sign-in</th><th /></tr></thead>
        <tbody>
          {(users.data ?? []).map((u) => (
            <tr key={u.username} className={u.active ? "" : "dismissed"}>
              <td><strong>{u.name}</strong><br /><span className="scene-id">{u.username}</span></td>
              <td>
                <select value={u.role} disabled={u.username === me.username} aria-label={`Role of ${u.username}`}
                  onChange={(e) => void run(() => accounts.editUser(u.username, { role: e.target.value as Role }))}>
                  {ROLES.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
                </select>
              </td>
              <td>
                <select value={u.unit} aria-label={`Unit of ${u.username}`} onChange={(e) => void run(() => accounts.editUser(u.username, { unit: e.target.value }))}>
                  {unitList.map((x) => <option key={x.id} value={x.id}>{x.path}</option>)}
                </select>
              </td>
              <td className="meta">{u.last_login_utc ?? "never"}</td>
              <td className="row-actions">
                {u.username !== me.username && (
                  <>
                    <button className="link" onClick={() => void run(async () => { const r = await accounts.resetPassword(u.username); setShown({ who: r.username, pw: r.temporary_password }); })}>Reset password</button>
                    <button className="link danger" onClick={() => void run(() => accounts.editUser(u.username, { active: !u.active }))}>{u.active ? "Disable" : "Enable"}</button>
                  </>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  );
}

function Units() {
  const units = useLoad(accounts.units);
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [error, setError] = useState<string | null>(null);
  const list = units.data ?? [];
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try { await accounts.addUnit(name, parent || list[0]?.id); setName(""); units.reload(); } catch (err) { setError(msg(err)); }
  };
  const depth = (u: UnitInfo) => u.path.split(" > ").length - 1;
  return (
    <>
      <h2>Add a unit</h2>
      <form className="admin-form" onSubmit={add}>
        <label className="field-block"><span>Name</span><input type="text" value={name} placeholder="e.g. Sindh provincial department" onChange={(e) => setName(e.target.value)} /></label>
        <label className="field-block"><span>Reports to</span>
          <select value={parent || list[0]?.id || ""} onChange={(e) => setParent(e.target.value)}>{list.map((u) => <option key={u.id} value={u.id}>{u.path}</option>)}</select></label>
        <button className="button primary" disabled={name.trim().length < 2}>Create unit</button>
      </form>
      <p className="meta">A user sees and acts on the assessments and uploads of their own unit and the units below it, never on sibling units. Benchmark tiles are shared.</p>
      {error && <p className="meta error-text" role="alert">{error}</p>}
      <h2>Organisation</h2>
      <ul className="unit-tree">
        {[...list].sort((a, b) => a.path.localeCompare(b.path)).map((u) => (
          <li key={u.id} style={{ paddingLeft: depth(u) * 20 }}><strong>{u.name}</strong> <span className="meta">{u.users} user{u.users === 1 ? "" : "s"}</span></li>
        ))}
      </ul>
    </>
  );
}

function ModelApproval() {
  const cur = useLoad<ApprovedModel>(accounts.approvedModel);
  const [pick, setPick] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const available = cur.data?.available ?? [];
  const sel = pick || cur.data?.default_model || "";
  const save = async () => {
    setError(null);
    setDone(false);
    try { await accounts.approveModel(sel, reason); setReason(""); setDone(true); cur.reload(); } catch (e) { setError(msg(e)); }
  };
  return (
    <>
      <h2>Approved default model</h2>
      <p className="meta">The model used for area alerts and uploads. It is chosen by approval, never by test score. A change is written to the audit log and to the decision log with your reason.</p>
      {cur.data && (
        <dl className="stats">
          <dt>Current</dt><dd>{available.find((m) => m.id === cur.data!.default_model)?.label ?? cur.data.default_model ?? "none"}</dd>
          <dt>Approved</dt><dd>{cur.data.approved_utc ?? "–"} by {cur.data.approved_by ?? "–"}</dd>
          <dt>Reason</dt><dd>{cur.data.reason ?? "–"}</dd>
        </dl>
      )}
      <div className="admin-form">
        <label className="field-block"><span>New default</span>
          <select value={sel} onChange={(e) => setPick(e.target.value)}>{available.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></label>
        <label className="field-block wide"><span>Reason (recorded)</span>
          <input type="text" value={reason} placeholder="Evidence for the change, e.g. experiment and result" onChange={(e) => setReason(e.target.value)} /></label>
        <button className="button primary" disabled={sel === cur.data?.default_model || reason.trim().length < 10} onClick={() => void save()}>Approve change</button>
      </div>
      {error && <p className="meta error-text" role="alert">{error}</p>}
      {done && <p className="notice">Default model changed and recorded.</p>}
    </>
  );
}

export function AuditView() {
  const [assessment, setAssessment] = useState("");
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [verify, setVerify] = useState<{ ok: boolean; entries: number; reason: string; first_bad_line: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    setError(null);
    accounts.audit(300, assessment.trim() || undefined).then((r) => setRows([...r].reverse())).catch((e) => setError(msg(e)));
  }, [assessment]);
  useEffect(load, [load]);
  const check = () => accounts.auditVerify().then(setVerify).catch((e) => setError(msg(e)));
  return (
    <>
      <h2>Audit log</h2>
      <p className="meta">Every action that changes or releases something, with the account that did it. Entries are chained by hash: an edited or removed line breaks the chain.</p>
      <div className="admin-form">
        <label className="field-block"><span>Assessment id (optional)</span>
          <input type="text" value={assessment} placeholder="e.g. upl_1a2b3c4d__unet_paired_mis__area" onChange={(e) => setAssessment(e.target.value)} /></label>
        <button className="button" onClick={load}>Refresh</button>
        <button className="button" onClick={() => void check()}>Verify the chain</button>
      </div>
      {verify && (
        <p className={`notice ${verify.ok ? "" : "bad"}`} role="status">
          {verify.ok ? `Chain intact: ${verify.entries} entries.` : `Chain broken at line ${verify.first_bad_line}: ${verify.reason}.`}
        </p>
      )}
      {error && <p className="meta error-text" role="alert">{error}</p>}
      <table className="audit-table">
        <thead><tr><th>#</th><th>Time (UTC)</th><th>Account</th><th>Action</th><th>Assessment</th><th>Detail</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.seq}>
              <td className="num">{r.seq}</td><td className="mono">{r.utc}</td><td>{r.actor}</td><td>{r.action.replace(/_/g, " ")}</td>
              <td className="mono">{r.assessment ?? ""}</td>
              <td className="meta">{Object.entries(r.detail).filter(([k]) => k !== "actor_unit").map(([k, v]) => `${k}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length === 0 && !error && <p className="empty-note">No entries.</p>}
    </>
  );
}

function Roles() {
  const roles = useLoad(accounts.roles), cat = useLoad(accounts.permissions);
  const [error, setError] = useState<string | null>(null);
  const [form, setForm] = useState({ key: "", label: "", description: "", based_on: "", permissions: [] as string[] });
  const [editing, setEditing] = useState<{ key: string; permissions: string[]; reason: string } | null>(null);
  const perms: PermissionCatalogue["permissions"] = cat.data?.permissions ?? [];
  const conflicts = cat.data?.conflicts ?? [];
  const clash = (held: string[]) => conflicts.find((c) => held.includes(c.a) && held.includes(c.b));
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn(); roles.reload(); } catch (e) { setError(msg(e)); } };
  const toggle = (list: string[], k: string) => (list.includes(k) ? list.filter((x) => x !== k) : [...list, k]);
  const chips = (r: RoleInfo) => r.permissions.map((p) => <code key={p} className="chip">{p}</code>);
  const picker = (held: string[], on: (next: string[]) => void) => (
    <fieldset className="perm-picker">
      {perms.map((p) => (
        <label key={p.key} title={p.description}><input type="checkbox" checked={held.includes(p.key)} onChange={() => on(toggle(held, p.key))} /> <code>{p.key}</code> <span className="meta">{p.description}</span></label>
      ))}
      {clash(held) && <p className="meta error-text" role="alert">A role cannot hold both {clash(held)!.a} and {clash(held)!.b}: {clash(held)!.reason}.</p>}
    </fieldset>
  );
  return (
    <>
      <h2>Roles ({roles.data?.length ?? 0})</h2>
      <p className="meta">A role is a set of permissions. The four built-in roles are fixed; to change what someone may do, create a role (optionally based on an existing one) and give it to them under Users.</p>
      {error && <p className="meta error-text" role="alert">{error}</p>}
      <table>
        <thead><tr><th>Role</th><th>Permissions</th><th>Users</th><th /></tr></thead>
        <tbody>
          {(roles.data ?? []).map((r) => (
            <tr key={r.key}>
              <td><strong>{r.label}</strong>{r.builtin && <span className="meta"> built-in</span>}<br /><span className="scene-id">{r.key}</span></td>
              <td>{editing?.key === r.key ? (
                <>{picker(editing.permissions, (permissions) => setEditing({ ...editing, permissions }))}
                  <label className="field-block"><span>Reason for the change</span><input type="text" value={editing.reason} onChange={(e) => setEditing({ ...editing, reason: e.target.value })} /></label></>
              ) : chips(r)}</td>
              <td>{r.users}</td>
              <td>{!r.builtin && (editing?.key === r.key ? (
                <><button className="button primary" disabled={editing.reason.trim().length < 10 || !!clash(editing.permissions)}
                  onClick={() => void run(async () => { await accounts.setRolePermissions(r.key, editing.permissions, editing.reason); setEditing(null); })}>Save</button>
                  <button className="button" onClick={() => setEditing(null)}>Cancel</button></>
              ) : (
                <><button className="button" onClick={() => setEditing({ key: r.key, permissions: r.permissions, reason: "" })}>Edit</button>
                  <button className="button" disabled={r.users > 0} title={r.users > 0 ? "Users still hold this role" : ""} onClick={() => void run(() => accounts.deleteRole(r.key))}>Delete</button></>
              ))}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>Create a role</h2>
      <form className="admin-form" onSubmit={(e: FormEvent) => { e.preventDefault(); void run(async () => { await accounts.addRole({ ...form, based_on: form.based_on || undefined }); setForm({ key: "", label: "", description: "", based_on: "", permissions: [] }); }); }}>
        <label className="field-block"><span>Key (letters, digits, underscore)</span><input type="text" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></label>
        <label className="field-block"><span>Name</span><input type="text" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} /></label>
        <label className="field-block"><span>Based on</span>
          <select value={form.based_on} onChange={(e) => setForm({ ...form, based_on: e.target.value })}><option value="">Nothing (start empty)</option>{(roles.data ?? []).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select></label>
        <label className="field-block"><span>Description</span><input type="text" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
        <div className="field-block">{picker(form.permissions, (permissions) => setForm({ ...form, permissions }))}</div>
        <button className="button primary" disabled={!form.key || !form.label || !!clash(form.permissions)}>Create role</button>
      </form>
    </>
  );
}

type Tab = "users" | "units" | "roles" | "model" | "audit";

/** Administrator and auditor screens (no imagery): users, units, approved model, audit log. */
export default function AdminShell({ user, tabs }: { user: User; tabs: Tab[] }) {
  const [tab, setTab] = useState<Tab>(tabs[0]);
  const label: Record<Tab, string> = { users: "Users", units: "Units", roles: "Roles", model: "Approved model", audit: "Audit log" };
  return (
    <div className="admin-body">
      <div className="admin-tabs">
        <div className="segmented" role="group" aria-label="Section">
          {tabs.map((t) => <button key={t} aria-pressed={tab === t} onClick={() => setTab(t)}>{label[t]}</button>)}
        </div>
      </div>
      <main className="admin-page">
        {tab === "users" && <Users me={user} />}
        {tab === "units" && <Units />}
        {tab === "roles" && <Roles />}
        {tab === "model" && <ModelApproval />}
        {tab === "audit" && <AuditView />}
      </main>
    </div>
  );
}
