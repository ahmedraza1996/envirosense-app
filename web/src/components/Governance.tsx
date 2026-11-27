import { Fragment, useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, AlertOctagon, BadgeCheck, Check, ClipboardList, Database, Download, FileText, Gauge, History, Lock, Plus, RefreshCw, RotateCcw, ShieldAlert,
  ShieldCheck, SlidersHorizontal, UserCheck, UserX, XCircle,
} from "lucide-react";
import {
  AccessRow, accounts, can, ControlRegister, Criterion, DataRegister, Decision, Framework, gov, Incident, Monitoring, Precision, RegistryModel, Risk,
  Scorecard, Threshold, ThresholdVersion, titleCase, User,
} from "../api";
import { Avatar, Badge, Button, Card, Empty, Field, Modal, Notice, PageHeader, Tone, when } from "../ui";

/** The governance screens: compliance, model registry, thresholds, monitoring, incidents, risks, data register, decision log and access review.
 *  Every number comes from the server; the server also decides who may change what (iam.route_policy). */

const msg = (e: unknown) => String(e).replace(/^Error: /, "");
const pct = (x: number | null | undefined, d = 0) => (x == null ? "–" : `${(x * 100).toFixed(d)}%`);

function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => { setLoading(true); setError(null); fn().then(setData).catch((e) => setError(msg(e))).finally(() => setLoading(false)); }, deps);   // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(reload, [reload]);
  return { data, error, reload, loading };
}

const STATUS_TONE: Record<string, Tone> = { met: "green", "partly met": "amber", "not met": "red", "not measured": "neutral", ok: "green", fail: "red",
  pass: "green", open: "red", investigating: "amber", closed: "neutral", reduced: "amber", accepted: "blue" };
const SEV_TONE: Record<string, Tone> = { low: "neutral", medium: "amber", high: "red", serious: "red" };
const Status = ({ s }: { s: string }) => <Badge tone={STATUS_TONE[s] ?? "neutral"} dot>{s}</Badge>;

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: Tone }) {
  return <div className={`kpi tone-${tone ?? "neutral"}`}><span className="kpi-label">{label}</span><strong>{value}</strong>{sub && <span className="kpi-sub">{sub}</span>}</div>;
}

function Loading({ l }: { l: { loading: boolean; error: string | null } }) {
  if (l.error) return <Notice tone="error">{l.error}</Notice>;
  return l.loading ? <p className="hint">Loading…</p> : null;
}

/* ---------------------------------------------------------------------------------------------- Compliance */

function FrameworkCard({ f, active, onClick }: { f: Framework; active: boolean; onClick: () => void }) {
  const w = (n: number) => `${(100 * n) / Math.max(f.total, 1)}%`;
  return (
    <button className={`fw-card${active ? " active" : ""}`} onClick={onClick} aria-pressed={active}>
      <span className="fw-name">{f.name}</span>
      <strong>{pct(f.score)}</strong>
      <span className="fw-bar" aria-hidden><i className="met" style={{ width: w(f.met) }} /><i className="part" style={{ width: w(f.partly) }} /></span>
      <span className="sub">{f.met} met · {f.partly} partly · {f.total - f.met - f.partly} not met, of {f.total}</span>
    </button>
  );
}

export function Compliance({ me }: { me: User }) {
  const reg = useLoad<ControlRegister>(gov.controls);
  const [fw, setFw] = useState<string | null>(null);
  const [stage, setStage] = useState("");
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const r = reg.data;
  const f = r?.frameworks.find((x) => x.key === fw) ?? null;
  const inFw = f ? new Set(f.requirements.flatMap((x) => x.controls)) : null;
  const list = (r?.controls ?? []).filter((c) => (!stage || c.stage === stage) && (!status || c.status === status) && (!inFw || inFw.has(c.id)));
  const run = async () => { const x = await gov.runChecks(); setNote(x.raised.length ? `${x.raised.length} incident(s) raised or updated by the checks.` : "Checks run: nothing to raise."); reg.reload(); };
  return (
    <>
      <PageHeader title="Compliance" subtitle="Every control is a check with a rule, an owner and evidence the system verifies now. Frameworks are scored from the controls; they are alignment targets, not certificates."
        actions={<>{can(me, "audit") && <Button icon={RefreshCw} onClick={() => void run()}>Run checks</Button>}
          <a className="button primary" href={gov.technicalFileUrl} download><Download size={16} aria-hidden />Technical file</a></>} />
      {note && <Notice tone="info" onClose={() => setNote(null)}>{note}</Notice>}
      <Loading l={reg} />
      {r && (
        <>
          <div className="kpis">
            <Kpi label="Controls met" value={`${r.counts.met} of ${r.controls.length}`} tone="green" />
            <Kpi label="Partly met" value={String(r.counts["partly met"])} tone="amber" />
            <Kpi label="Not met" value={String(r.counts["not met"])} tone="red" />
            <Kpi label="Not measured yet" value={String(r.counts["not measured"])} />
            <Kpi label="Tests last run" value={r.tests_run_utc ? when(r.tests_run_utc) : "never"} sub={`checked ${when(r.checked_utc)}`} />
          </div>
          <h2 className="section-label">Frameworks</h2>
          <div className="fw-grid">{r.frameworks.map((x) => <FrameworkCard key={x.key} f={x} active={fw === x.key} onClick={() => setFw(fw === x.key ? null : x.key)} />)}</div>
          {f && (
            <Card title={f.name} subtitle={<><strong>Role:</strong> {f.role} <strong>How it is applied:</strong> {f.how}</>}>
              <div className="table-wrap"><table className="data compact">
                <thead><tr><th>Requirement</th><th>Controls that carry it</th><th>Status</th></tr></thead>
                <tbody>{f.requirements.map((q) => (
                  <tr key={q.id}><td><strong>{q.id}</strong> <span className="sub">{q.title}</span></td>
                    <td><div className="chips">{q.controls.map((c) => <button key={c} className="chip link-chip" onClick={() => setOpen(c)}>{c}</button>)}</div></td>
                    <td><Status s={q.status} /></td></tr>))}</tbody>
              </table></div>
            </Card>
          )}
          <h2 className="section-label">Controls{f ? ` in ${f.name}` : ""}</h2>
          <Card flush>
            <div className="toolbar">
              <select value={stage} onChange={(e) => setStage(e.target.value)} aria-label="Stage"><option value="">All stages</option>{r.stages.map((s) => <option key={s}>{s}</option>)}</select>
              <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status"><option value="">Any status</option>{["met", "partly met", "not met", "not measured"].map((s) => <option key={s}>{s}</option>)}</select>
              <span className="toolbar-count">{list.length} of {r.controls.length}</span>
            </div>
            <div className="table-wrap"><table className="data compact clickable">
              <thead><tr><th>Control</th><th>Stage</th><th>Owner</th><th>Status</th></tr></thead>
              <tbody>{list.map((c) => (
                <Fragment key={c.id}>
                  <tr onClick={() => setOpen(open === c.id ? null : c.id)} tabIndex={0}>
                    <td><strong>{c.id}</strong> {c.name}<div className="sub">{c.rule}</div></td><td className="nowrap">{c.stage}</td><td className="nowrap">{c.owner}</td><td><Status s={c.status} /></td>
                  </tr>
                  {open === c.id && (
                    <tr className="detail-row"><td colSpan={4}>
                      <ul className="evidence">{c.evidence.map((e, i) => (
                        <li key={i}><Status s={e.status} /><span className="ev-type">{e.type}</span><code>{e.ref ?? e.check}</code><span>{e.detail}</span></li>))}</ul>
                      <div className="chips">{Object.entries(c.frameworks).flatMap(([k, v]) => v.map((x) => <span key={k + x} className="chip">{k.toUpperCase()} {x}</span>))}</div>
                    </td></tr>
                  )}
                </Fragment>
              ))}</tbody>
            </table></div>
          </Card>
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Model registry */

const fmt = (v: Criterion["measured"]) => (v == null ? "not measured" : typeof v === "boolean" ? (v ? "yes" : "no") : v.toFixed(3));

function ScorecardTable({ sc }: { sc: Scorecard }) {
  return (
    <div className="table-wrap"><table className="data compact">
      <thead><tr><th>Criterion</th><th>Pass mark</th><th>Measured</th><th>Result</th></tr></thead>
      <tbody>{sc.criteria.map((c) => (
        <tr key={c.id}><td><strong>{c.id}</strong> {c.text}<div className="sub">{c.group}</div></td><td className="nowrap">{c.op} {String(c.value)}</td>
          <td className="nowrap">{fmt(c.measured)}</td><td><Status s={c.status} /></td></tr>))}</tbody>
    </table></div>
  );
}

export function ModelRegistry({ me }: { me: User }) {
  const reg = useLoad(gov.models);
  const approved = useLoad(accounts.approvedModel);
  const [sel, setSel] = useState<string | null>(null);
  const [detail, setDetail] = useState<{ scorecard: Scorecard } | null>(null);
  const [card, setCard] = useState<{ draft: boolean; markdown: string } | null>(null);
  const [asking, setAsking] = useState<RegistryModel | null>(null);
  const [reason, setReason] = useState(""), [exception, setException] = useState("");
  const [error, setError] = useState<string | null>(null), [done, setDone] = useState<string | null>(null);
  const models = reg.data?.models ?? [];
  const current = models.find((m) => m.id === sel) ?? models[0] ?? null;
  useEffect(() => {
    if (!current) return;
    setDetail(null); setCard(null);
    void gov.model(current.id).then(setDetail).catch(() => undefined);
    void gov.card(current.id).then(setCard).catch(() => undefined);
  }, [current?.id]);   // eslint-disable-line react-hooks/exhaustive-deps
  const mayApprove = can(me, "model_approve");
  const prev = approved.data?.previous;
  const submit = async () => {
    if (!asking) return;
    setError(null);
    try {
      const r = await accounts.approveModel(asking.id, reason, exception);
      setDone(r.approval?.status === "pending" ? `Request ${r.approval.id} filed: a second administrator must approve it (Approvals).` : `${asking.label} is now the approved model.`);
      setAsking(null); setReason(""); setException(""); reg.reload(); approved.reload();
    } catch (e) { setError(msg(e)); }
  };
  return (
    <>
      <PageHeader title="Model registry" subtitle="Every model the server can run, checked against the acceptance criteria written before the final runs. The release gate opens only when every criterion passes; otherwise a release needs a written exception that the approver sees." />
      {done && <Notice tone="success" onClose={() => setDone(null)}>{done}</Notice>}
      <Loading l={reg} />
      <Card flush>
        <div className="table-wrap"><table className="data clickable">
          <thead><tr><th>Model</th><th>Status</th><th className="num">Test</th><th className="num">Hold</th><th>Criteria</th><th>Release gate</th><th>Card</th><th className="end" /></tr></thead>
          <tbody>{models.map((m) => (
            <tr key={m.id} onClick={() => setSel(m.id)} className={current?.id === m.id ? "selected" : ""} tabIndex={0}>
              <td><strong>{m.label}</strong><div className="mono-sm">{m.id} · {m.run}</div></td>
              <td>{m.status === "approved" ? <Badge tone="green" icon={BadgeCheck}>Approved</Badge> : <Badge tone="neutral">Candidate</Badge>}</td>
              <td className="num">{m.test_score?.toFixed(3) ?? "–"}</td><td className="num">{m.hold_score?.toFixed(3) ?? "–"}</td>
              <td className="nowrap">{m.passed} pass{m.failed.length ? ` · ${m.failed.length} fail` : ""}{m.missing.length ? ` · ${m.missing.length} not measured` : ""}</td>
              <td>{m.gate_open ? <Badge tone="green" icon={Check}>Open</Badge> : <Badge tone="red" icon={Lock}>Closed</Badge>}</td>
              <td>{m.card_saved ? <Badge tone="green">Saved</Badge> : <Badge tone="amber">Draft</Badge>}</td>
              <td className="end">{mayApprove && m.status !== "approved" && (
                <Button size="sm" icon={m.id === prev ? RotateCcw : Check} onClick={(e) => { e.stopPropagation(); setError(null); setReason(m.id === prev ? "Roll back to the previous approved model" : ""); setAsking(m); }}>
                  {m.id === prev ? "Roll back" : "Request approval"}</Button>)}</td>
            </tr>))}</tbody>
        </table></div>
      </Card>
      {current && (
        <div className="stack-gap" style={{ marginTop: 20 }}>
          <Card title={`Scorecard: ${current.label}`} subtitle={`Pass marks written ${reg.data?.criteria.written_utc ?? ""}, before the final runs.`}>
            {detail ? <ScorecardTable sc={detail.scorecard} /> : <p className="hint">Loading…</p>}
          </Card>
          <Card title="Model card" subtitle={card?.draft ? "Draft generated now from the run's records: the run has not saved its own card yet (criterion AC-7b)." : "Saved by the training run."}>
            {card ? <pre className="md">{card.markdown}</pre> : <p className="hint">Loading…</p>}
          </Card>
        </div>
      )}
      <Modal open={!!asking} title={asking?.id === prev ? "Roll back the approved model" : "Request approval of a model"} subtitle={asking?.label} width={600} onClose={() => setAsking(null)}
        footer={<><Button onClick={() => setAsking(null)}>Cancel</Button>
          <Button variant="primary" disabled={reason.trim().length < 10 || (!asking?.gate_open && exception.trim().length < 20)} onClick={() => void submit()}>Submit request</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        {asking && !asking.gate_open && (
          <Notice tone="warning"><strong>The release gate is closed.</strong> Missed: {asking.failed.join(", ") || "none"}; not measured: {asking.missing.join(", ") || "none"}.
            It can be released only with a written exception; the approver sees it and it is kept in the decision log.</Notice>)}
        <Field label="Reason" hint="At least 10 characters: cite the experiment and its result." wide><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
        {asking && !asking.gate_open && <Field label="Written exception" hint="At least 20 characters: why release although the criteria above are not met." wide>
          <textarea rows={3} value={exception} onChange={(e) => setException(e.target.value)} /></Field>}
        <p className="hint">A second eligible administrator must approve before the change takes effect.</p>
      </Modal>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Thresholds */

export function Thresholds({ me }: { me: User }) {
  const list = useLoad(accounts.thresholds);
  const [hist, setHist] = useState<{ key: string; rows: ThresholdVersion[] } | null>(null);
  const [edit, setEdit] = useState<Threshold | null>(null);
  const [value, setValue] = useState(""), [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null), [done, setDone] = useState<string | null>(null);
  const submit = async () => {
    if (!edit) return;
    setError(null);
    try {
      const r = await accounts.setThreshold(edit.key, Number(value), reason);
      setDone(r.approval.status === "pending" ? `Request ${r.approval.id} filed: another administrator must approve it.` : `${edit.key} changed.`);
      setEdit(null); list.reload();
    } catch (e) { setError(msg(e)); }
  };
  return (
    <>
      <PageHeader title="Thresholds" subtitle="Values that change what the system flags, alerts or abstains on. A value is never edited: a change is a new version, made only when a second administrator approves it." />
      {done && <Notice tone="success" onClose={() => setDone(null)}>{done}</Notice>}
      <Loading l={list} />
      <Card flush>
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Threshold</th><th className="num">Value</th><th>Allowed</th><th>Version</th><th>Set by</th><th className="end" /></tr></thead>
          <tbody>{(list.data ?? []).map((t) => (
            <tr key={t.key}>
              <td><strong>{t.description ?? t.key}</strong><div className="mono-sm">{t.key}</div></td>
              <td className="num"><strong>{t.value}</strong></td>
              <td className="nowrap sub-cell">{t.min ?? "–"} to {t.max ?? "–"}</td>
              <td className="nowrap"><span className="mono-sm">v{t.version}</span><div className="sub">{when(t.effective_utc)}</div></td>
              <td><div className="stack"><span>{t.set_by}</span><span className="sub">{t.decision_ref}</span></div></td>
              <td className="end"><div className="row-tools">
                <Button size="sm" icon={History} onClick={() => void accounts.thresholdHistory(t.key).then((rows) => setHist({ key: t.key, rows }))}>History</Button>
                {can(me, "model_approve") && <Button size="sm" icon={SlidersHorizontal} onClick={() => { setError(null); setValue(String(t.value)); setReason(""); setEdit(t); }}>Change</Button>}
              </div></td>
            </tr>))}</tbody>
        </table></div>
      </Card>
      <Modal open={!!hist} title={`History of ${hist?.key ?? ""}`} onClose={() => setHist(null)}>
        <table className="data compact"><thead><tr><th>Value</th><th>From</th><th>Set by</th><th>Why</th></tr></thead>
          <tbody>{(hist?.rows ?? []).map((h, i) => <tr key={i}><td>{h.value}</td><td className="nowrap">{h.effective_utc}</td><td>{h.set_by}</td><td className="sub">{h.note}</td></tr>)}</tbody></table>
      </Modal>
      <Modal open={!!edit} title={`Change ${edit?.key ?? ""}`} subtitle={edit?.description} onClose={() => setEdit(null)}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" disabled={reason.trim().length < 10 || value === ""} onClick={() => void submit()}>Submit change</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="New value" hint={`Between ${edit?.min} and ${edit?.max}. Now ${edit?.value}.`}><input type="number" step="any" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
        <Field label="Reason" hint="At least 10 characters: what was measured on validation data that supports the new value." wide><input type="text" value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Monitoring */

const precisionRows = (o: Record<string, Precision>) => Object.entries(o).map(([k, p]) => (
  <tr key={k}><td>{titleCase(k)}</td><td className="num">{p.decided}</td><td className="num">{p.confirmed}</td><td className="num">{p.dismissed}</td><td className="num">{p.retracted}</td><td className="num"><strong>{pct(p.precision)}</strong></td></tr>));

export function MonitoringView() {
  const m = useLoad<Monitoring>(gov.monitoring);
  const d = m.data;
  return (
    <>
      <PageHeader title="Monitoring" subtitle="Is the system still doing what it was approved to do? Live accuracy comes from what reviewers confirm or dismiss. Crossing a floor raises an incident automatically."
        actions={<Button icon={RefreshCw} onClick={m.reload}>Refresh</Button>} />
      <Loading l={m} />
      {d && (
        <>
          <div className="kpis">
            <Kpi label="Live precision" value={pct(d.live_precision.overall.precision)} tone={d.live_precision.below_floor ? "red" : d.live_precision.enough_data ? "green" : "neutral"}
              sub={d.live_precision.enough_data ? `floor ${pct(d.live_precision.floor)}, last ${d.live_precision.window} decided` : `${d.live_precision.overall.decided} of ${d.live_precision.window} decided alerts needed`} />
            <Kpi label="Abstained (30 days)" value={pct(d.abstention.rate)} sub={`${d.abstention.abstained} of ${d.abstention.total} assessments`} />
            <Kpi label="Unusual uploads (30 days)" value={pct(d.drift.last_30_days.share)} tone={d.drift.rising ? "red" : "neutral"}
              sub={`before: ${pct(d.drift.previous_30_days.share)}`} />
            <Kpi label="Possible rubber stamps" value={pct(d.review_behaviour.share_flagged)} tone={(d.review_behaviour.share_flagged ?? 0) > 0.5 ? "red" : "neutral"}
              sub={`${d.review_behaviour.flagged} of ${d.review_behaviour.measured} confirmations`} />
            <Kpi label="Open incidents" value={String(d.incidents.open)} tone={d.incidents.urgent ? "red" : "neutral"} sub={`${d.incidents.urgent} high or serious`} />
          </div>
          <div className="two-col">
            <Card title="Live precision by model" subtitle="Share of decided alerts people confirmed; a retracted alert counts as wrong.">
              <table className="data compact"><thead><tr><th>Model</th><th className="num">Decided</th><th className="num">Conf.</th><th className="num">Dism.</th><th className="num">Retr.</th><th className="num">Precision</th></tr></thead>
                <tbody>{precisionRows(d.live_precision.by_model)}</tbody></table>
              {!Object.keys(d.live_precision.by_model).length && <Empty icon={Gauge} title="No decided alerts yet" />}
            </Card>
            <Card title="Live precision by hazard type">
              <table className="data compact"><thead><tr><th>Hazard</th><th className="num">Decided</th><th className="num">Conf.</th><th className="num">Dism.</th><th className="num">Retr.</th><th className="num">Precision</th></tr></thead>
                <tbody>{precisionRows(d.live_precision.by_hazard)}</tbody></table>
            </Card>
            <Card title="Why alerts were dismissed" subtitle="The most recent reasons, to find what the model gets wrong.">
              {d.live_precision.dismissal_reasons.length ? <ul className="reasons">{d.live_precision.dismissal_reasons.map((r, i) => <li key={i}><span>{r.note}</span><span className="sub">{r.reviewed_by}, {r.utc}</span></li>)}</ul>
                : <Empty icon={ClipboardList} title="None yet" />}
            </Card>
            <Card title="Review behaviour" subtitle={`Confirmations decided in under ${d.review_behaviour.seconds} s or without opening the evidence. Median time to confirm: ${d.review_behaviour.median_seconds ?? "–"} s.`}>
              <table className="data compact"><thead><tr><th>Reviewer</th><th className="num">Confirmed</th><th className="num">Flagged</th></tr></thead>
                <tbody>{d.review_behaviour.by_reviewer.map((r) => <tr key={r.actor}><td>{r.actor}</td><td className="num">{r.confirmations}</td><td className="num">{r.flagged}</td></tr>)}</tbody></table>
            </Card>
            <Card title="Input drift by month" subtitle="Uploads unlike the training images, blank or cloud share, brightness.">
              <table className="data compact"><thead><tr><th>Month</th><th className="num">Uploads</th><th className="num">Unusual</th><th className="num">Blank/cloud</th><th className="num">Brightness</th></tr></thead>
                <tbody>{d.drift.months.map((r) => <tr key={r.month}><td>{r.month}</td><td className="num">{r.uploads}</td><td className="num">{r.unusual}</td><td className="num">{pct(r.empty_share)}</td><td className="num">{r.brightness ?? "–"}</td></tr>)}</tbody></table>
            </Card>
            <Card title="Why the system abstained (30 days)">
              {d.abstention.reasons.length ? <table className="data compact"><tbody>{d.abstention.reasons.map((r) => <tr key={r.reason}><td>{titleCase(r.reason.toLowerCase().replace(/_/g, "-"))}</td><td className="num">{r.n}</td></tr>)}</tbody></table>
                : <Empty icon={Activity} title="No abstentions" />}
            </Card>
          </div>
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Incidents */

const KINDS = ["wrong_alert", "model_quality", "data_drift", "security", "audit_chain", "access", "other"];

export function ReportIncident({ open, onClose, onDone, assessment, alertId }: { open: boolean; onClose: () => void; onDone?: (i: Incident) => void; assessment?: string; alertId?: string }) {
  const [form, setForm] = useState({ kind: alertId ? "wrong_alert" : "other", severity: "medium", title: "", description: "" });
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setError(null); setForm({ kind: alertId ? "wrong_alert" : "other", severity: "medium", title: alertId ? `Problem with alert ${alertId}` : "", description: "" }); } }, [open, alertId]);
  const submit = async () => {
    setError(null);
    try { const i = await gov.openIncident({ ...form, assessment, alert_id: alertId }); onDone?.(i); onClose(); } catch (e) { setError(msg(e)); }
  };
  return (
    <Modal open={open} title="Report an incident" subtitle="Something went wrong or may have: a wrong alert, a strange result, a security worry. An administrator or officer follows it up." width={560} onClose={onClose}
      footer={<><Button onClick={onClose}>Cancel</Button><Button variant="primary" icon={AlertOctagon} disabled={form.title.trim().length < 5} onClick={() => void submit()}>Report</Button></>}>
      {error && <Notice tone="error">{error}</Notice>}
      <div className="form-grid">
        <Field label="Kind"><select value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>{KINDS.map((k) => <option key={k} value={k}>{titleCase(k.replace(/_/g, "-"))}</option>)}</select></Field>
        <Field label="Severity" hint={form.severity === "serious" ? "Serious: the supervisor must know within 24 hours." : undefined}>
          <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>{["low", "medium", "high", "serious"].map((s) => <option key={s}>{s}</option>)}</select></Field>
        <Field label="Title" wide><input type="text" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="What happened" wide><textarea rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></Field>
      </div>
      {assessment && <p className="hint">Linked to {assessment}{alertId ? `, alert ${alertId}` : ""}.</p>}
    </Modal>
  );
}

export function Incidents({ me }: { me: User }) {
  const [state, setState] = useState("open");
  const list = useLoad(() => gov.incidents(state === "all" ? undefined : state === "open" ? undefined : state), [state]);
  const [sel, setSel] = useState<Incident | null>(null);
  const [reporting, setReporting] = useState(false);
  const [act, setAct] = useState<"assess" | "note" | "close" | "reopen" | null>(null);
  const [form, setForm] = useState({ note: "", severity: "", cause: "", resolution: "" });
  const [error, setError] = useState<string | null>(null);
  const manage = can(me, "incident_manage");
  const rows = (list.data ?? []).filter((i) => state !== "open" || i.state !== "closed");
  const openOne = (id: number) => void gov.incident(id).then(setSel).catch((e) => setError(msg(e)));
  const run = async () => {
    if (!sel || !act) return;
    setError(null);
    try { setSel(await gov.incidentAction(sel.id, act, { ...form, severity: form.severity || undefined })); setAct(null); list.reload(); } catch (e) { setError(msg(e)); }
  };
  return (
    <>
      <PageHeader title="Incidents" subtitle="Wrong alerts, quality floors crossed, drift, security. Anyone can report one; administrators and officers assess and close them with the cause. Nothing is deleted."
        actions={<Button variant="primary" icon={Plus} onClick={() => setReporting(true)}>Report incident</Button>} />
      <div className="tabs" role="tablist">
        {["open", "closed", "all"].map((s) => <button key={s} role="tab" aria-selected={state === s} onClick={() => setState(s)}>{titleCase(s)}</button>)}
      </div>
      <Loading l={list} />
      <div className={sel ? "split" : ""}>
        <Card flush>
          {rows.length === 0 && !list.loading ? <Empty icon={ShieldCheck} title="No incidents here" /> : (
            <div className="table-wrap"><table className="data clickable">
              <thead><tr><th>#</th><th>Incident</th><th>Severity</th><th>State</th><th>Opened</th></tr></thead>
              <tbody>{rows.map((i) => (
                <tr key={i.id} onClick={() => openOne(i.id)} className={sel?.id === i.id ? "selected" : ""} tabIndex={0}>
                  <td className="mono-sm">{i.id}</td>
                  <td><strong>{i.title}</strong><div className="sub">{titleCase(i.kind.replace(/_/g, "-"))} · {i.source === "check" ? "raised by a check" : `reported by ${i.opened_by}`}</div></td>
                  <td><Badge tone={SEV_TONE[i.severity]}>{i.severity}</Badge></td><td><Status s={i.state} /></td><td className="sub-cell">{when(i.opened_utc)}</td>
                </tr>))}</tbody>
            </table></div>
          )}
        </Card>
        {sel && (
          <Card title={`#${sel.id} ${sel.title}`} subtitle={<><Badge tone={SEV_TONE[sel.severity]}>{sel.severity}</Badge> <Status s={sel.state} /> {titleCase(sel.kind.replace(/_/g, "-"))}</>}
            actions={<Button size="sm" icon={XCircle} onClick={() => setSel(null)}>Close panel</Button>}>
            {error && <Notice tone="error">{error}</Notice>}
            {sel.description && <p className="pre-line">{sel.description}</p>}
            {Object.keys(sel.links ?? {}).length > 0 && <p className="sub">Linked: {Object.entries(sel.links).map(([k, v]) => `${k} ${v}`).join(", ")}</p>}
            {sel.state === "closed" && <dl className="facts"><dt>Cause</dt><dd>{sel.cause}</dd><dt>Resolution</dt><dd>{sel.resolution}</dd><dt>Closed by</dt><dd>{sel.closed_by}</dd></dl>}
            <h3 className="section-label">Timeline</h3>
            <ol className="timeline">{(sel.events ?? []).map((e, i) => <li key={i}><Avatar name={e.actor} size={22} /><div><strong>{e.action}</strong> by {e.actor} <span className="sub">{e.utc}</span>{e.note && <p className="pre-line">{e.note}</p>}</div></li>)}</ol>
            {manage && (
              <div className="btn-row">
                {sel.state !== "closed" && <Button onClick={() => { setForm({ note: "", severity: "", cause: "", resolution: "" }); setAct("assess"); }}>Assess</Button>}
                {sel.state !== "closed" && <Button onClick={() => { setForm({ note: "", severity: "", cause: "", resolution: "" }); setAct("note"); }}>Add note</Button>}
                {sel.state !== "closed" && <Button variant="primary" icon={Check} onClick={() => { setForm({ note: "", severity: "", cause: "", resolution: "" }); setAct("close"); }}>Close with cause</Button>}
                {sel.state === "closed" && <Button icon={RotateCcw} onClick={() => { setForm({ note: "", severity: "", cause: "", resolution: "" }); setAct("reopen"); }}>Reopen</Button>}
              </div>
            )}
          </Card>
        )}
      </div>
      <ReportIncident open={reporting} onClose={() => setReporting(false)} onDone={(i) => { list.reload(); setSel(i); }} />
      <Modal open={!!act} title={act === "close" ? "Close the incident" : act === "assess" ? "Assess the incident" : act === "reopen" ? "Reopen the incident" : "Add a note"} onClose={() => setAct(null)}
        footer={<><Button onClick={() => setAct(null)}>Cancel</Button><Button variant="primary" onClick={() => void run()}>Save</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        {act === "close" ? (
          <>
            <Field label="Cause" hint="What went wrong (at least 5 characters)." wide><input type="text" value={form.cause} onChange={(e) => setForm({ ...form, cause: e.target.value })} /></Field>
            <Field label="Resolution" hint="What was done about it (at least 10 characters)." wide><textarea rows={3} value={form.resolution} onChange={(e) => setForm({ ...form, resolution: e.target.value })} /></Field>
          </>
        ) : (
          <>
            <Field label="Note" wide><textarea rows={3} value={form.note} onChange={(e) => setForm({ ...form, note: e.target.value })} /></Field>
            {act === "assess" && <Field label="Severity after assessment"><select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })}>
              <option value="">unchanged</option>{["low", "medium", "high", "serious"].map((s) => <option key={s}>{s}</option>)}</select></Field>}
          </>
        )}
      </Modal>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Risks */

export function RiskRegister({ me }: { me: User }) {
  const list = useLoad(gov.risks);
  const [edit, setEdit] = useState<Risk | null>(null);
  const [form, setForm] = useState<Partial<Risk> & { reason: string; controlsText: string }>({ reason: "", controlsText: "" });
  const [error, setError] = useState<string | null>(null);
  const [cell, setCell] = useState<[number, number] | null>(null);
  const rows = (list.data ?? []).filter((r) => !cell || (r.likelihood === cell[0] && r.severity === cell[1]));
  const grid = useMemo(() => { const g: Record<string, number> = {}; (list.data ?? []).filter((r) => r.status !== "closed").forEach((r) => { g[`${r.likelihood},${r.severity}`] = (g[`${r.likelihood},${r.severity}`] ?? 0) + 1; }); return g; }, [list.data]);
  const save = async () => {
    if (!edit) return;
    setError(null);
    try {
      await gov.updateRisk(edit.id, { likelihood: form.likelihood, severity: form.severity, status: form.status, owner: form.owner, next_review: form.next_review,
        controls: form.controlsText.split(/[\s,]+/).filter(Boolean), reason: form.reason });
      setEdit(null); list.reload();
    } catch (e) { setError(msg(e)); }
  };
  const mayEdit = can(me, "risk_manage");
  return (
    <>
      <PageHeader title="Risk register" subtitle="What can go wrong at each stage, how likely and how bad (1 to 5), the controls that reduce it, the owner and when it is looked at again. Every edit needs a reason and is logged." />
      <Loading l={list} />
      <div className="risk-top">
        <Card title="Heat map" subtitle="Open risks by likelihood and severity. Click a cell to filter.">
          <div className="heat" role="grid">
            {[5, 4, 3, 2, 1].map((sv) => (
              <div className="heat-row" key={sv} role="row"><span className="heat-axis">{sv}</span>
                {[1, 2, 3, 4, 5].map((lk) => {
                  const n = grid[`${lk},${sv}`] ?? 0, score = lk * sv;
                  return <button key={lk} role="gridcell" className={`heat-cell s${score >= 15 ? 3 : score >= 8 ? 2 : 1}${cell && cell[0] === lk && cell[1] === sv ? " on" : ""}`}
                    onClick={() => setCell(cell && cell[0] === lk && cell[1] === sv ? null : [lk, sv])} aria-label={`likelihood ${lk}, severity ${sv}: ${n} risks`}>{n || ""}</button>;
                })}
              </div>))}
            <div className="heat-row"><span className="heat-axis" />{[1, 2, 3, 4, 5].map((lk) => <span key={lk} className="heat-axis">{lk}</span>)}</div>
            <p className="sub">Severity (up) by likelihood (across)</p>
          </div>
        </Card>
      </div>
      <Card flush>
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Risk</th><th>Stage</th><th className="num">L×S</th><th>Controls</th><th>Owner</th><th>Status</th><th>Review by</th><th className="end" /></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.id}>
              <td><strong>{r.id}</strong> {r.risk}<div className="sub">{r.cause}</div></td><td className="nowrap">{titleCase(r.stage.replace(/ /g, "-"))}</td>
              <td className="num"><Badge tone={r.score >= 15 ? "red" : r.score >= 8 ? "amber" : "green"}>{r.likelihood}×{r.severity}={r.score}</Badge></td>
              <td><div className="chips">{r.controls.map((c) => <span key={c} className="chip">{c}</span>)}</div>{r.planned && <div className="sub">Planned: {r.planned}</div>}</td>
              <td>{r.owner}</td><td><Status s={r.status} /></td>
              <td className="nowrap">{r.overdue ? <Badge tone="red">Overdue {r.next_review}</Badge> : r.next_review}</td>
              <td className="end">{mayEdit && <Button size="sm" onClick={() => { setError(null); setForm({ ...r, reason: "", controlsText: r.controls.join(", ") }); setEdit(r); }}>Edit</Button>}</td>
            </tr>))}</tbody>
        </table></div>
      </Card>
      <Modal open={!!edit} title={`${edit?.id ?? ""}: ${edit?.risk ?? ""}`} width={600} onClose={() => setEdit(null)}
        footer={<><Button onClick={() => setEdit(null)}>Cancel</Button><Button variant="primary" disabled={form.reason.trim().length < 10} onClick={() => void save()}>Save</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <div className="form-grid">
          <Field label="Likelihood (1 to 5)"><input type="number" min={1} max={5} value={form.likelihood ?? ""} onChange={(e) => setForm({ ...form, likelihood: Number(e.target.value) })} /></Field>
          <Field label="Severity (1 to 5)"><input type="number" min={1} max={5} value={form.severity ?? ""} onChange={(e) => setForm({ ...form, severity: Number(e.target.value) })} /></Field>
          <Field label="Status"><select value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value as Risk["status"] })}>{["open", "reduced", "accepted", "closed"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Next review"><input type="date" value={form.next_review ?? ""} onChange={(e) => setForm({ ...form, next_review: e.target.value })} /></Field>
          <Field label="Owner" wide><input type="text" value={form.owner ?? ""} onChange={(e) => setForm({ ...form, owner: e.target.value })} /></Field>
          <Field label="Controls" hint="Control ids from the Compliance page, e.g. P1, H4." wide><input type="text" value={form.controlsText} onChange={(e) => setForm({ ...form, controlsText: e.target.value })} /></Field>
          <Field label="Reason for the change" hint="At least 10 characters; kept in the audit log with the old and new values." wide><input type="text" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} /></Field>
        </div>
      </Modal>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Data register */

export function DataRegisterView() {
  const d = useLoad<DataRegister>(gov.data);
  const r = d.data;
  return (
    <>
      <PageHeader title="Data register" subtitle="Every dataset and every uploaded image: where it came from, under which licence, who confirmed the right to use it, its quality, and when it is deleted." />
      <Loading l={d} />
      {r && (
        <>
          <Card title="Training and evaluation data">
            <table className="data compact"><thead><tr><th>Dataset</th><th>Use</th><th className="num">Pairs</th><th>Source</th><th>Licence</th><th>Checks</th></tr></thead>
              <tbody>{r.datasets.map((x) => <tr key={x.name}><td><strong>{x.name}</strong><div className="sub">{x.datasheet}</div></td><td>{x.use}</td><td className="num">{x.pairs.toLocaleString()}</td>
                <td>{x.source}</td><td>{x.licence.startsWith("to confirm") ? <Badge tone="amber">{x.licence}</Badge> : x.licence}</td><td className="sub">{x.verified}; hashes in {x.hashes}</td></tr>)}</tbody></table>
          </Card>
          <h2 className="section-label">Uploaded imagery {r.retention_days ? `(deleted after ${r.retention_days} days)` : "(no retention period set: kept until deleted)"}</h2>
          <Card flush>
            {r.uploads.length === 0 ? <Empty icon={Database} title="No uploads" /> : (
              <div className="table-wrap"><table className="data compact">
                <thead><tr><th>Upload</th><th>Source and licence</th><th>Right confirmed by</th><th>Quality</th><th>Metadata removed</th><th>Delete after</th></tr></thead>
                <tbody>{r.uploads.map((u) => (
                  <tr key={u.id}>
                    <td><strong>{u.name}</strong><div className="mono-sm">{u.id} · {u.created} · {u.created_by}</div></td>
                    <td>{u.source ?? <Badge tone="red">not recorded</Badge>}<div className="sub">{u.licence ?? "no licence"}</div></td>
                    <td>{u.rights_confirmed_by ?? <Badge tone="red">nobody</Badge>}</td>
                    <td>{u.unusual == null ? <span className="sub">not measured</span> : u.unusual ? <Badge tone="red">Unusual</Badge> : <Badge tone="green">Typical</Badge>}
                      {u.abstained && <div><Badge tone="amber">Not assessed</Badge></div>}{u.empty_share != null && <div className="sub">{pct(u.empty_share)} blank or cloud</div>}</td>
                    <td className="sub">{u.metadata_removed?.length ? u.metadata_removed.join(", ") : "none found"}</td>
                    <td className="nowrap">{u.delete_after ?? "–"}</td>
                  </tr>))}</tbody>
              </table></div>
            )}
          </Card>
        </>
      )}
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Decision log */

export function DecisionLog() {
  const d = useLoad<Decision[]>(gov.decisions);
  return (
    <>
      <PageHeader title="Decision log" subtitle="Every change of model, threshold, role or scope, and every release exception, with its reason and the people who took it. Rows cannot be changed or deleted." />
      <Loading l={d} />
      <Card flush>
        <div className="table-wrap"><table className="data">
          <thead><tr><th>When</th><th>Kind</th><th>Decision</th><th>Decided by</th><th>Approved by</th></tr></thead>
          <tbody>{(d.data ?? []).map((x) => (
            <tr key={x.id}><td className="nowrap sub-cell">{x.utc.slice(0, 10)}</td><td><Badge tone={x.kind === "model_release" ? "violet" : x.kind === "threshold" ? "amber" : "neutral"}>{x.kind.replace(/_/g, " ")}</Badge></td>
              <td><strong>{x.decision}</strong><div className="sub">{x.reason}</div></td><td>{x.decided_by}</td><td>{x.approved_by ?? "–"}</td></tr>))}</tbody>
        </table></div>
      </Card>
    </>
  );
}

/* ---------------------------------------------------------------------------------------------- Access review */

export function AccessReview({ me }: { me: User }) {
  const list = useLoad<AccessRow[]>(gov.accessReviews);
  const [dis, setDis] = useState<AccessRow | null>(null);
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const act = async (u: AccessRow, decision: "keep" | "disable", n = "") => {
    setError(null);
    try { await gov.reviewAccess(u.username, decision, n); setDis(null); list.reload(); } catch (e) { setError(msg(e)); }
  };
  const due = (list.data ?? []).filter((r) => r.due).length;
  return (
    <>
      <PageHeader title="Access review" subtitle="Every 3 months an administrator confirms that each active account is still needed. Nobody reviews their own account. Disabling ends the account's sessions at once." />
      {error && !dis && <Notice tone="error" onClose={() => setError(null)}>{error}</Notice>}
      {due > 0 && <Notice tone="warning">{due} account{due === 1 ? "" : "s"} due for review.</Notice>}
      <Loading l={list} />
      <Card flush>
        <div className="table-wrap"><table className="data">
          <thead><tr><th>Account</th><th>Role</th><th>Two-step</th><th>Last sign-in</th><th>Last review</th><th className="end" /></tr></thead>
          <tbody>{(list.data ?? []).map((u) => (
            <tr key={u.username} className={u.active ? "" : "muted"}>
              <td><div className="who"><Avatar name={u.name} /><div><strong>{u.name}</strong><span className="mono-sm">{u.username}</span></div></div></td>
              <td>{u.role}</td><td>{u.two_step ? <Badge tone="green">On</Badge> : <Badge tone="neutral">Off</Badge>}</td>
              <td className="sub-cell">{when(u.last_login_utc)}</td>
              <td>{u.last_review ? <div className="stack"><span>{u.last_review.decision} on {u.last_review.reviewed}</span><span className="sub">by {u.last_review.reviewed_by}</span></div> : <span className="sub">never</span>}
                {u.due && <div><Badge tone="amber">Due</Badge></div>}</td>
              <td className="end">{u.active && u.username !== me.username && (
                <div className="row-tools">
                  <Button size="sm" icon={UserCheck} onClick={() => void act(u, "keep")}>Still needed</Button>
                  <Button size="sm" variant="danger" icon={UserX} onClick={() => { setNote(""); setError(null); setDis(u); }}>Disable</Button>
                </div>)}</td>
            </tr>))}</tbody>
        </table></div>
      </Card>
      <Modal open={!!dis} title={`Disable ${dis?.name ?? ""}?`} onClose={() => setDis(null)}
        footer={<><Button onClick={() => setDis(null)}>Cancel</Button><Button variant="danger" disabled={note.trim().length < 5} onClick={() => dis && void act(dis, "disable", note)}>Disable</Button></>}>
        {error && <Notice tone="error">{error}</Notice>}
        <Field label="Why is the account no longer needed?" wide><input type="text" value={note} onChange={(e) => setNote(e.target.value)} /></Field>
      </Modal>
    </>
  );
}

export const GOV_ICONS = { compliance: ShieldCheck, registry: FileText, thresholds: SlidersHorizontal, monitoring: Activity, incidents: ShieldAlert, risks: AlertOctagon,
  data: Database, decisions: ClipboardList, access: UserCheck };
