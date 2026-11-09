import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BadgeCheck, Building2, Check, ClipboardCheck, Copy, Cpu, KeyRound, Lock, LucideIcon, Network, Pencil, Plus, RefreshCw, ScrollText, Search,
  ShieldCheck, SlidersHorizontal, Trash2, UserCheck, UserPlus, Users as UsersIcon, UserX, XCircle,
} from "lucide-react";
import {
  accounts, ApprovalOutcome, ApprovalRequest, ApprovedModel, AuditEntry, PermissionCatalogue, RoleInfo, UnitInfo, User,
} from "../api";
import { Avatar, Badge, Button, Card, Empty, Field, IconButton, Modal, Notice, PageHeader, roleTone, Tone, when } from "../ui";

const msg = (e: unknown) => String(e).replace(/^Error: /, "");

function useLoad<T>(fn: () => Promise<T>) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => { setLoading(true); fn().then(setData).catch((e) => setError(msg(e))).finally(() => setLoading(false)); }, []);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(reload, [reload]);
  return { data, error, reload, loading };
}

/** Runs an action, reports its failure, and reloads what it changed. */
function useAction(after: () => void) {
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>) => { setError(null); try { await fn(); after(); return true; } catch (e) { setError(msg(e)); return false; } };
  return { error, setError, run };
}

function TemporaryPassword({ who, pw, onClose }: { who: string; pw: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false);
  const copy = () => { void navigator.clipboard?.writeText(pw).then(() => { setCopied(true); setTimeout(() => setCopied(false), 1800); }); };
  return (
    <Modal open title="Temporary password" subtitle={<>For <strong>{who}</strong>. Shown once; it is not stored anywhere.</>} onClose={onClose}
      footer={<Button variant="primary" onClick={onClose}>Done</Button>}>
      <div className="secret"><code>{pw}</code><Button size="sm" icon={copied ? Check : Copy} onClick={copy}>{copied ? "Copied" : "Copy"}</Button></div>
      <p className="hint">Pass it on privately. {who} must choose their own password at first sign-in, and every session they had is ended.</p>
    </Modal>
  );
}

/* ------------------------------------------------------------------------------------------------ Users */

const unitName = (path: string) => path.split(" > ").pop() ?? path;
const unitParent = (path: string) => path.split(" > ").slice(0, -1).pop();

export function Users({ me }: { me: User }) {
  const users = useLoad(accounts.users), units = useLoad(accounts.units), roles = useLoad(accounts.roles);
  const { error, setError, run } = useAction(() => { users.reload(); units.reload(); });
  const [q, setQ] = useState(""), [roleF, setRoleF] = useState(""), [statusF, setStatusF] = useState("");
  const [adding, setAdding] = useState(false), [editing, setEditing] = useState<User | null>(null), [resetting, setResetting] = useState<User | null>(null);
  const [shown, setShown] = useState<{ who: string; pw: string } | null>(null);
  const [form, setForm] = useState({ username: "", name: "", role: "analyst", unit: "" });
  const [edit, setEdit] = useState({ name: "", role: "", unit: "", active: true });
  const roleList = roles.data ?? [], unitList = units.data ?? [];
  const list = useMemo(() => (users.data ?? []).filter((u) =>
    (!q || `${u.name} ${u.username}`.toLowerCase().includes(q.toLowerCase())) && (!roleF || u.role === roleF) &&
    (!statusF || (statusF === "active" ? u.active : !u.active))), [users.data, q, roleF, statusF]);

  const openAdd = () => { setError(null); setForm({ username: "", name: "", role: roleList.find((r) => r.key === "analyst") ? "analyst" : roleList[0]?.key ?? "", unit: me.unit }); setAdding(true); };
  const openEdit = (u: User) => { setError(null); setEdit({ name: u.name, role: u.role, unit: u.unit, active: u.active }); setEditing(u); };
  const create = async () => {
    const ok = await run(async () => { const u = await accounts.addUser({ ...form, unit: form.unit || me.unit }); setShown({ who: u.username, pw: u.temporary_password ?? "" }); });
    if (ok) setAdding(false);
  };
  const save = async () => { if (editing && await run(() => accounts.editUser(editing.username, { name: edit.name, role: edit.role, unit: edit.unit, active: edit.active }))) setEditing(null); };
  const reset = async () => {
    if (!resetting) return;
    const who = resetting.username;
    const ok = await run(async () => { const r = await accounts.resetPassword(who); setShown({ who: r.username, pw: r.temporary_password }); });
    if (ok) setResetting(null);
  };
  const status = (u: User) => !u.active ? <Badge tone="red" dot>Disabled</Badge>
    : u.must_change_password ? <Badge tone="amber" dot>Must set password</Badge> : <Badge tone="green" dot>Active</Badge>;

  return (
    <>
      <PageHeader title="Users" subtitle="People who can sign in, the role each holds and the unit they belong to."
        actions={<Button variant="primary" icon={UserPlus} onClick={openAdd}>Add user</Button>} />
      {error && !adding && !editing && !resetting && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <Card flush>
        <div className="toolbar">
          <label className="search"><Search size={16} aria-hidden /><input type="search" placeholder="Search name or username" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search users" /></label>
          <select value={roleF} onChange={(e) => setRoleF(e.target.value)} aria-label="Filter by role"><option value="">All roles</option>{roleList.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select>
          <select value={statusF} onChange={(e) => setStatusF(e.target.value)} aria-label="Filter by status"><option value="">Any status</option><option value="active">Active</option><option value="disabled">Disabled</option></select>
          <span className="toolbar-count">{list.length} of {users.data?.length ?? 0}</span>
        </div>
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>User</th><th>Role</th><th>Unit</th><th>Status</th><th>Last sign-in</th><th className="end" /></tr></thead>
            <tbody>
              {list.map((u) => (
                <tr key={u.username} className={u.active ? "" : "muted"}>
                  <td><div className="who"><Avatar name={u.name} /><div><strong>{u.name}</strong><span className="mono-sm">{u.username}</span></div></div></td>
                  <td><Badge tone={roleTone(u.role)}>{u.role_label}</Badge></td>
                  <td title={u.unit_path}><div className="stack"><span>{unitName(u.unit_path)}</span>{unitParent(u.unit_path) && <span className="sub">in {unitParent(u.unit_path)}</span>}</div></td>
                  <td>{status(u)}</td>
                  <td className="sub-cell" title={u.last_login_utc ?? ""}>{when(u.last_login_utc)}</td>
                  <td className="end">
                    <div className="row-tools">
                      <IconButton icon={Pencil} label={`Edit ${u.username}`} onClick={() => openEdit(u)} />
                      {u.username !== me.username && <IconButton icon={KeyRound} label={`Reset password of ${u.username}`} onClick={() => { setError(null); setResetting(u); }} />}
                      {u.username !== me.username && <IconButton icon={u.active ? UserX : UserCheck} label={u.active ? `Disable ${u.username}` : `Enable ${u.username}`} tone={u.active ? "danger" : undefined}
                        onClick={() => void run(() => accounts.editUser(u.username, { active: !u.active }))} />}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!users.loading && list.length === 0 && <Empty icon={UsersIcon} title="No users match">Change the search or the filters.</Empty>}
        </div>
      </Card>

      <Modal open={adding} title="Add a user" subtitle="They receive a temporary password and must choose their own at first sign-in." onClose={() => setAdding(false)}
        footer={<><Button onClick={() => setAdding(false)}>Cancel</Button><Button variant="primary" icon={UserPlus} disabled={!form.username || !form.name} onClick={() => void create()}>Create user</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-grid">
          <Field label="Username" hint="3 to 32 characters: letters, digits, dot, dash, underscore."><input type="text" autoFocus value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></Field>
          <Field label="Full name"><input type="text" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
          <Field label="Role" hint={roleList.find((r) => r.key === form.role)?.description} wide>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>{roleList.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select></Field>
          <Field label="Unit" hint="They see this unit and the units below it." wide>
            <select value={form.unit} onChange={(e) => setForm({ ...form, unit: e.target.value })}>{unitList.map((u) => <option key={u.id} value={u.id}>{u.path}</option>)}</select></Field>
        </div>
      </Modal>

      <Modal open={!!editing} title={editing ? `Edit ${editing.name}` : ""} subtitle={editing?.username} onClose={() => setEditing(null)}
        footer={<><Button onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" onClick={() => void save()}>Save changes</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        {editing && (
          <div className="form-grid">
            <Field label="Full name" wide><input type="text" value={edit.name} onChange={(e) => setEdit({ ...edit, name: e.target.value })} /></Field>
            <Field label="Role" wide hint={editing.username === me.username ? "You cannot change your own role." : undefined}>
              <select value={edit.role} disabled={editing.username === me.username} onChange={(e) => setEdit({ ...edit, role: e.target.value })}>{roleList.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select></Field>
            <Field label="Unit" wide><select value={edit.unit} onChange={(e) => setEdit({ ...edit, unit: e.target.value })}>{unitList.map((u) => <option key={u.id} value={u.id}>{u.path}</option>)}</select></Field>
            <label className="switch wide"><input type="checkbox" checked={edit.active} disabled={editing.username === me.username} onChange={(e) => setEdit({ ...edit, active: e.target.checked })} />
              <span className="track" aria-hidden /><span>Account is active<small>A disabled account cannot sign in and its sessions end at once.</small></span></label>
          </div>
        )}
      </Modal>

      <Modal open={!!resetting} title="Reset password?" subtitle={resetting ? `${resetting.name} (${resetting.username})` : ""} onClose={() => setResetting(null)}
        footer={<><Button onClick={() => setResetting(null)}>Cancel</Button><Button variant="danger" icon={KeyRound} onClick={() => void reset()}>Reset password</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <p>A new temporary password is generated and shown once. The current password stops working and every session this person has is ended. They choose a new password at next sign-in. The reset is recorded in the audit log.</p>
      </Modal>
      {shown && <TemporaryPassword who={shown.who} pw={shown.pw} onClose={() => setShown(null)} />}
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ Units */

export function Units() {
  const units = useLoad(accounts.units);
  const { error, setError, run } = useAction(() => units.reload());
  const [dialog, setDialog] = useState<{ mode: "add" | "edit"; unit?: UnitInfo; parent?: string } | null>(null);
  const [name, setName] = useState(""), [parent, setParent] = useState("");
  const list = useMemo(() => [...(units.data ?? [])].sort((a, b) => a.path.localeCompare(b.path)), [units.data]);
  const depth = (u: UnitInfo) => u.path.split(" > ").length - 1;
  const open = (d: NonNullable<typeof dialog>) => { setError(null); setName(d.mode === "edit" ? d.unit!.name : ""); setParent(d.mode === "edit" ? d.unit!.parent ?? "" : d.parent ?? list[0]?.id ?? ""); setDialog(d); };
  const submit = async () => {
    if (!dialog) return;
    const ok = await run(() => dialog.mode === "add" ? accounts.addUnit(name, parent) : accounts.editUnit(dialog.unit!.id, { name, parent: parent && parent !== dialog.unit!.parent ? parent : undefined }));
    if (ok) setDialog(null);
  };
  return (
    <>
      <PageHeader title="Units" subtitle="The organisation tree. A user sees and acts on the work of their own unit and the units below it, never a sibling. Benchmark tiles are shared."
        actions={<Button variant="primary" icon={Plus} onClick={() => open({ mode: "add" })}>Add unit</Button>} />
      {error && !dialog && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <Card flush>
        <ul className="org">
          {list.map((u) => (
            <li key={u.id} style={{ paddingLeft: 20 + depth(u) * 28 }}>
              {depth(u) > 0 && <span className="elbow" style={{ left: 20 + (depth(u) - 1) * 28 + 12 }} aria-hidden />}
              <span className="org-icon"><Building2 size={18} aria-hidden /></span>
              <div className="org-name"><strong>{u.name}</strong>{!u.parent && <Badge tone="violet">Top unit</Badge>}</div>
              <Badge tone="neutral" icon={UsersIcon}>{u.users} {u.users === 1 ? "user" : "users"}</Badge>
              <div className="row-tools">
                <IconButton icon={Plus} label={`Add a unit under ${u.name}`} onClick={() => open({ mode: "add", parent: u.id })} />
                <IconButton icon={Pencil} label={`Rename or move ${u.name}`} onClick={() => open({ mode: "edit", unit: u })} />
              </div>
            </li>
          ))}
        </ul>
        {!units.loading && list.length === 0 && <Empty icon={Network} title="No units yet" />}
      </Card>
      <Modal open={!!dialog} title={dialog?.mode === "edit" ? "Rename or move unit" : "Add a unit"} onClose={() => setDialog(null)}
        footer={<><Button onClick={() => setDialog(null)}>Cancel</Button><Button variant="primary" disabled={name.trim().length < 2} onClick={() => void submit()}>{dialog?.mode === "edit" ? "Save" : "Create unit"}</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-grid">
          <Field label="Name" wide><input type="text" autoFocus value={name} placeholder="e.g. Sindh provincial disaster management" onChange={(e) => setName(e.target.value)} /></Field>
          {!(dialog?.mode === "edit" && !dialog.unit?.parent) && (
            <Field label="Reports to" wide>
              <select value={parent} onChange={(e) => setParent(e.target.value)}>{list.filter((u) => u.id !== dialog?.unit?.id).map((u) => <option key={u.id} value={u.id}>{u.path}</option>)}</select></Field>
          )}
        </div>
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ Roles */

const PERM_GROUPS: { title: string; keys: string[] }[] = [
  { title: "Administration", keys: ["users", "audit", "model_approve"] },
  { title: "Imagery and assessment", keys: ["view", "assess", "upload", "delete_own_upload", "delete_upload", "geo_offset"] },
  { title: "Review and release", keys: ["review", "review_read", "approve", "export"] },
];

function PermissionPicker({ catalogue, held, onChange }: { catalogue: PermissionCatalogue; held: string[]; onChange: (next: string[]) => void }) {
  const byKey = new Map(catalogue.permissions.map((p) => [p.key, p]));
  const clash = catalogue.conflicts.find((c) => held.includes(c.a) && held.includes(c.b));
  const toggle = (k: string) => onChange(held.includes(k) ? held.filter((x) => x !== k) : [...held, k]);
  const known = new Set(PERM_GROUPS.flatMap((g) => g.keys));
  const groups = [...PERM_GROUPS, { title: "Other", keys: catalogue.permissions.map((p) => p.key).filter((k) => !known.has(k)) }].filter((g) => g.keys.some((k) => byKey.has(k)));
  return (
    <div className="perm-picker">
      {groups.map((g) => (
        <fieldset key={g.title}>
          <legend>{g.title}</legend>
          {g.keys.filter((k) => byKey.has(k)).map((k) => {
            const p = byKey.get(k)!;
            return (
              <label key={k} className={held.includes(k) ? "on" : ""}>
                <input type="checkbox" checked={held.includes(k)} onChange={() => toggle(k)} />
                <span className="perm-text"><strong>{p.description}</strong><code>{k}</code></span>
                {p.sensitive && <Badge tone="amber" icon={Lock}>Sensitive</Badge>}
              </label>
            );
          })}
        </fieldset>
      ))}
      {clash && <Notice tone="warning">A role cannot hold both <code>{clash.a}</code> and <code>{clash.b}</code>: {clash.reason}.</Notice>}
    </div>
  );
}

export function Roles() {
  const roles = useLoad(accounts.roles), cat = useLoad(accounts.permissions);
  const { error, setError, run } = useAction(() => roles.reload());
  const [note, setNote] = useState<string | null>(null);
  const [creating, setCreating] = useState(false), [editing, setEditing] = useState<RoleInfo | null>(null), [removing, setRemoving] = useState<RoleInfo | null>(null);
  const [form, setForm] = useState({ key: "", label: "", description: "", based_on: "", permissions: [] as string[] });
  const [held, setHeld] = useState<string[]>([]), [reason, setReason] = useState("");
  const catalogue = cat.data ?? { permissions: [], conflicts: [] };
  const clash = (list: string[]) => catalogue.conflicts.some((c) => list.includes(c.a) && list.includes(c.b));
  const sensitive = new Set(catalogue.permissions.filter((p) => p.sensitive).map((p) => p.key));
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 32);

  const create = async () => {
    const ok = await run(async () => { await accounts.addRole({ ...form, based_on: form.based_on || undefined }); setNote(`Role “${form.label}” created.`); });
    if (ok) setCreating(false);
  };
  const saveEdit = async () => {
    if (!editing) return;
    const ok = await run(async () => {
      const r = await accounts.setRolePermissions(editing.key, held, reason);
      setNote(r.approval.status === "pending" ? `Request ${r.approval.id} filed for “${editing.label}”: another administrator must approve it before it takes effect (see Approvals).` : `Role “${editing.label}” updated.`);
    });
    if (ok) setEditing(null);
  };
  return (
    <>
      <PageHeader title="Roles" subtitle="A role is a set of permissions. The four built-in roles are fixed; to change what someone may do, create a role and assign it under Users."
        actions={<Button variant="primary" icon={Plus} onClick={() => { setError(null); setForm({ key: "", label: "", description: "", based_on: "", permissions: [] }); setCreating(true); }}>Create role</Button>} />
      {note && <Notice tone="success" onClose={() => setNote(null)}>{note}</Notice>}
      {error && !creating && !editing && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      <div className="role-grid">
        {(roles.data ?? []).map((r) => (
          <section key={r.key} className="card role-card">
            <div className="role-head">
              <span className={`role-icon tone-${roleTone(r.key)}`}><ShieldCheck size={18} aria-hidden /></span>
              <div><h2>{r.label}</h2><code className="mono-sm">{r.key}</code></div>
              {r.builtin ? <Badge tone="neutral" icon={Lock}>Built-in</Badge> : <Badge tone="blue">Custom</Badge>}
            </div>
            <p className="role-desc">{r.description || "No description."}</p>
            <div className="chips">{r.permissions.map((p) => <span key={p} className={`chip${sensitive.has(p) ? " sensitive" : ""}`}>{p}</span>)}</div>
            <div className="role-foot">
              <Badge tone="neutral" icon={UsersIcon}>{r.users} {r.users === 1 ? "user" : "users"}</Badge>
              {!r.builtin && (
                <div className="row-tools">
                  <IconButton icon={Pencil} label={`Edit ${r.label}`} onClick={() => { setError(null); setHeld(r.permissions); setReason(""); setEditing(r); }} />
                  <IconButton icon={Trash2} tone="danger" label={r.users ? "Users still hold this role" : `Delete ${r.label}`} disabled={r.users > 0} onClick={() => { setError(null); setRemoving(r); }} />
                </div>
              )}
            </div>
          </section>
        ))}
      </div>

      <Modal open={creating} title="Create a role" subtitle="Start from an existing role or from nothing, then choose what it may do." width={620} onClose={() => setCreating(false)}
        footer={<><Button onClick={() => setCreating(false)}>Cancel</Button><Button variant="primary" icon={Plus} disabled={!form.key || !form.label || clash(form.permissions)} onClick={() => void create()}>Create role</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-grid">
          <Field label="Name"><input type="text" autoFocus value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value, key: form.key && form.key !== slug(form.label) ? form.key : slug(e.target.value) })} /></Field>
          <Field label="Key" hint="Letters, digits, underscore."><input type="text" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></Field>
          <Field label="Based on" hint="Its permissions are copied; add more below." wide>
            <select value={form.based_on} onChange={(e) => setForm({ ...form, based_on: e.target.value })}><option value="">Nothing (start empty)</option>{(roles.data ?? []).map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}</select></Field>
          <Field label="Description" wide><input type="text" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
        </div>
        <h3 className="section-label">Permissions</h3>
        <PermissionPicker catalogue={catalogue} held={form.permissions} onChange={(permissions) => setForm({ ...form, permissions })} />
      </Modal>

      <Modal open={!!editing} title={editing ? `Edit ${editing.label}` : ""} subtitle="The change needs a second administrator's approval unless you are the only one." width={620} onClose={() => setEditing(null)}
        footer={<><Button onClick={() => setEditing(null)}>Cancel</Button><Button variant="primary" disabled={reason.trim().length < 10 || clash(held)} onClick={() => void saveEdit()}>Submit change</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <PermissionPicker catalogue={catalogue} held={held} onChange={setHeld} />
        <Field label="Reason for the change" hint="At least 10 characters. Recorded with the request." wide><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>

      <Modal open={!!removing} title="Delete role?" subtitle={removing?.label} onClose={() => setRemoving(null)}
        footer={<><Button onClick={() => setRemoving(null)}>Cancel</Button><Button variant="danger" icon={Trash2} onClick={() => removing && void run(() => accounts.deleteRole(removing.key)).then(() => setRemoving(null))}>Delete role</Button></>}>
        <p>The role and its permissions are removed. No user holds it. This is recorded in the audit log.</p>
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ Approvals */

const KIND: Record<string, { icon: LucideIcon; label: string }> = {
  model_approval: { icon: Cpu, label: "Default model" },
  threshold_change: { icon: SlidersHorizontal, label: "Threshold" },
  role_permissions: { icon: ShieldCheck, label: "Role permissions" },
};
const STATE: Record<string, { tone: Tone; label: string }> = {
  pending: { tone: "amber", label: "Waiting" }, approved: { tone: "green", label: "Approved" }, rejected: { tone: "red", label: "Rejected" },
  withdrawn: { tone: "neutral", label: "Withdrawn" }, expired: { tone: "neutral", label: "Expired" }, failed: { tone: "red", label: "Failed" },
};

function summary(r: ApprovalRequest) {
  const p = r.payload as { reason?: string; value?: number; permissions?: string[] };
  const change = r.kind === "model_approval" ? <>Make <strong>{r.subject}</strong> the default model</>
    : r.kind === "threshold_change" ? <>Set <strong>{r.subject.replace(/_/g, " ")}</strong> to <strong>{p.value}</strong></>
      : <>Set the permissions of role <strong>{r.subject}</strong> to {(p.permissions ?? []).length ? (p.permissions ?? []).map((x) => <span key={x} className="chip">{x}</span>) : "none"}</>;
  return { change, reason: p.reason };
}

export function Approvals({ me, onChange }: { me: User; onChange: () => void }) {
  const list = useLoad(() => accounts.approvals());
  const { error, setError, run } = useAction(() => { list.reload(); onChange(); });
  const [tab, setTab] = useState<"waiting" | "decided">("waiting");
  const [rejecting, setRejecting] = useState<ApprovalRequest | null>(null), [approving, setApproving] = useState<ApprovalRequest | null>(null), [note, setNote] = useState("");
  const rows = list.data ?? [], waiting = rows.filter((r) => r.state === "pending"), decided = rows.filter((r) => r.state !== "pending");
  const decide = async (r: ApprovalRequest, approve: boolean) => { if (await run(() => accounts.decideApproval(r.id, approve, note))) { setRejecting(null); setApproving(null); setNote(""); } };
  return (
    <>
      <PageHeader title="Approvals" subtitle="A change to the default model, a threshold or a custom role's permissions takes effect only when someone other than the person who asked approves it." />
      <div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "waiting"} onClick={() => setTab("waiting")}>Waiting <span className="count">{waiting.length}</span></button>
        <button role="tab" aria-selected={tab === "decided"} onClick={() => setTab("decided")}>Decided <span className="count">{decided.length}</span></button>
      </div>
      {error && !rejecting && !approving && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      {tab === "waiting" && (
        waiting.length === 0 ? <Card><Empty icon={ClipboardCheck} title="Nothing is waiting">Requests appear here when someone asks to change the model, a threshold or a role.</Empty></Card> : (
          <div className="stack-gap">
            {waiting.map((r) => {
              const K = KIND[r.kind] ?? { icon: ClipboardCheck, label: r.kind }, s = summary(r);
              return (
                <section key={r.id} className="card approval">
                  <span className="approval-icon"><K.icon size={20} aria-hidden /></span>
                  <div className="approval-main">
                    <div className="approval-top"><Badge tone="blue">{K.label}</Badge><span className="sub">Request {r.id}</span></div>
                    <p className="approval-change">{s.change}</p>
                    {s.reason && <blockquote>{s.reason}</blockquote>}
                    <p className="sub"><Avatar name={r.requested_by} size={20} /> {r.requested_by === me.username ? "You" : r.requested_by} asked {when(r.requested_utc)} · expires {r.expires_utc.slice(0, 10)}</p>
                  </div>
                  <div className="approval-actions">
                    {r.can_decide && <><Button variant="primary" icon={Check} onClick={() => { setError(null); setNote(""); setApproving(r); }}>Approve</Button>
                      <Button icon={XCircle} onClick={() => { setError(null); setNote(""); setRejecting(r); }}>Reject</Button></>}
                    {r.can_withdraw && <Button onClick={() => void run(() => accounts.withdrawApproval(r.id))}>Withdraw</Button>}
                    {!r.can_decide && !r.can_withdraw && <span className="sub">Not yours to decide</span>}
                  </div>
                </section>
              );
            })}
          </div>
        )
      )}
      {tab === "decided" && (
        <Card flush>
          {decided.length === 0 ? <Empty icon={ClipboardCheck} title="No decisions yet" /> : (
            <div className="table-wrap"><table className="data">
              <thead><tr><th>Change</th><th>Result</th><th>Asked by</th><th>Decided by</th></tr></thead>
              <tbody>{decided.map((r) => {
                const s = summary(r), st = STATE[r.state] ?? STATE.pending;
                return (
                  <tr key={r.id}>
                    <td><div className="stack"><span>{s.change}</span>{s.reason && <span className="sub">{s.reason}</span>}</div></td>
                    <td><Badge tone={st.tone} dot>{st.label}</Badge>{r.self_approved && <div className="sub">only eligible approver</div>}<div className="sub">{when(r.decided_utc)}</div></td>
                    <td>{r.requested_by}</td>
                    <td>{r.decided_by ?? "–"}{r.decision_note && <div className="sub">{r.decision_note}</div>}</td>
                  </tr>
                );
              })}</tbody>
            </table></div>
          )}
        </Card>
      )}
      <Modal open={!!approving} title="Approve this change?" subtitle={approving ? `Request ${approving.id}` : ""} onClose={() => setApproving(null)}
        footer={<><Button onClick={() => setApproving(null)}>Cancel</Button><Button variant="primary" icon={Check} onClick={() => approving && void decide(approving, true)}>Approve and apply</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        {approving && <p className="approval-change">{summary(approving).change}</p>}
        <Field label="Note (optional)" wide><input type="text" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
        <p className="hint">The change is made at once, in the same step as your approval, and recorded with both names.</p>
      </Modal>
      <Modal open={!!rejecting} title="Reject this change?" subtitle={rejecting ? `Request ${rejecting.id}` : ""} onClose={() => setRejecting(null)}
        footer={<><Button onClick={() => setRejecting(null)}>Cancel</Button><Button variant="danger" disabled={note.trim().length < 5} onClick={() => rejecting && void decide(rejecting, false)}>Reject</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Reason (required)" wide><input type="text" autoFocus value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ Approved model */

export function ModelApproval() {
  const cur = useLoad<ApprovedModel>(accounts.approvedModel);
  const [pick, setPick] = useState(""), [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<ApprovalOutcome | null>(null);
  const available = cur.data?.available ?? [];
  const name = (id?: string | null) => available.find((m) => m.id === id)?.label ?? id ?? "None";
  const sel = pick || cur.data?.default_model || "";
  const save = async () => {
    setError(null); setDone(null);
    try { const r = await accounts.approveModel(sel, reason); setReason(""); setDone(r.approval ?? null); cur.reload(); } catch (e) { setError(msg(e)); }
  };
  return (
    <>
      <PageHeader title="Approved model" subtitle="The model used for area alerts and uploads. It is chosen by approval, never by test score." />
      <div className="two-col">
        <Card title="Current default">
          <div className="model-now"><span className="approval-icon"><Cpu size={22} aria-hidden /></span><div><strong>{name(cur.data?.default_model)}</strong><code className="mono-sm">{cur.data?.default_model ?? "none"}</code></div><Badge tone="green" icon={BadgeCheck}>Approved</Badge></div>
          <dl className="facts">
            <dt>Approved</dt><dd>{cur.data?.approved_utc ?? "–"}</dd>
            <dt>By</dt><dd>{cur.data?.approved_by ?? "–"}</dd>
            <dt>Previous</dt><dd>{name(cur.data?.previous)}</dd>
            <dt>Reason</dt><dd>{cur.data?.reason ?? "–"}</dd>
          </dl>
        </Card>
        <Card title="Request a change" subtitle="A second administrator approves it before it takes effect; the reason goes to the decision log.">
          {error && <Notice tone="error">{error}</Notice>}
          {done && <Notice tone={done.status === "pending" ? "info" : "success"}>{done.status === "pending" ? `Request ${done.id} filed. Another administrator must approve it before the default changes (see Approvals).` : "Default model changed and recorded."}</Notice>}
          <div className="form-grid single">
            <Field label="New default"><select value={sel} onChange={(e) => setPick(e.target.value)}>{available.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</select></Field>
            <Field label="Reason" hint="At least 10 characters. Cite the experiment and its result."><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
            <div><Button variant="primary" icon={Check} disabled={sel === cur.data?.default_model || reason.trim().length < 10} onClick={() => void save()}>Submit change</Button></div>
          </div>
        </Card>
      </div>
    </>
  );
}

/* ------------------------------------------------------------------------------------------------ Audit */

const actionTone = (a: string): Tone => /denied|failed|retract|delete|reject/.test(a) ? "red" : /approv|confirm|propos|review|decision/.test(a) ? "blue" : /export|offset|model|threshold|role/.test(a) ? "amber" : /login|logout|password/.test(a) ? "violet" : "neutral";

export function AuditView() {
  const [assessment, setAssessment] = useState("");
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [verify, setVerify] = useState<{ ok: boolean; entries: number; reason: string; first_bad_line: number | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const load = useCallback(() => {
    setError(null); setLoading(true);
    accounts.audit(300, assessment.trim() || undefined).then((r) => setRows([...r].reverse())).catch((e) => setError(msg(e))).finally(() => setLoading(false));
  }, [assessment]);
  useEffect(load, [load]);
  const check = () => accounts.auditVerify().then(setVerify).catch((e) => setError(msg(e)));
  return (
    <>
      <PageHeader title="Audit log" subtitle="Every action that changes or releases something, with the account that did it. Entries are chained by hash: an edited or removed entry breaks the chain."
        actions={<><Button icon={RefreshCw} onClick={load}>Refresh</Button><Button variant="primary" icon={ShieldCheck} onClick={() => void check()}>Verify chain</Button></>} />
      {verify && (verify.ok
        ? <Notice tone="success"><strong>Chain intact.</strong> {verify.entries} entries verified from the first to the last.</Notice>
        : <Notice tone="error"><strong>Chain broken</strong> at entry {verify.first_bad_line}: {verify.reason}.</Notice>)}
      {error && <Notice tone="error">{error}</Notice>}
      <Card flush>
        <div className="toolbar">
          <label className="search wide"><Search size={16} aria-hidden /><input type="search" value={assessment} placeholder="Filter by assessment id, e.g. upl_1a2b3c4d__unet_paired_mis__area" onChange={(e) => setAssessment(e.target.value)} aria-label="Assessment id" /></label>
          <span className="toolbar-count">{rows.length} entries</span>
        </div>
        <div className="table-wrap">
          <table className="data audit">
            <thead><tr><th className="num">#</th><th>Time (UTC)</th><th>Account</th><th>Action</th><th>Detail</th></tr></thead>
            <tbody>
              {rows.map((r) => {
                const detail = Object.entries(r.detail).filter(([k]) => !["actor_unit", "actor_role"].includes(k)).map(([k, v]) => `${k.replace(/_/g, " ")}: ${typeof v === "object" ? JSON.stringify(v) : v}`).join("  ·  ");
                return (
                  <tr key={r.seq}>
                    <td className="num mono-sm">{r.seq}</td><td className="mono-sm nowrap">{r.utc}</td>
                    <td><div className="who tight"><Avatar name={r.actor} size={24} /><span>{r.actor}</span></div></td>
                    <td><Badge tone={actionTone(r.action)}>{r.action.replace(/_/g, " ")}</Badge></td>
                    <td className="detail" title={detail}>{r.assessment && <code className="mono-sm">{r.assessment}</code>}<span>{detail}</span></td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!loading && rows.length === 0 && !error && <Empty icon={ScrollText} title="No entries" />}
        </div>
      </Card>
    </>
  );
}
