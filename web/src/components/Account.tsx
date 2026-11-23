import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { BadgeCheck, ChevronDown, Eye, EyeOff, KeyRound, LogOut, ScrollText, ShieldCheck, Smartphone, Users, Lock } from "lucide-react";
import { accounts, DemoAccounts, TwoStepNeeded, User } from "../api";
import { Avatar, Badge, Button, Field, Modal, Notice } from "../ui";

const msg = (e: unknown) => String(e).replace(/^Error: /, "");

function Secret({ value, onChange, autoComplete, label, hint, autoFocus }: { value: string; onChange: (v: string) => void; autoComplete: string; label: string; hint?: ReactNode; autoFocus?: boolean }) {
  const [show, setShow] = useState(false);
  return (
    <Field label={label} hint={hint} wide>
      <span className="input-icon">
        <Lock size={16} aria-hidden />
        <input type={show ? "text" : "password"} autoComplete={autoComplete} autoFocus={autoFocus} value={value} onChange={(e) => onChange(e.target.value)} />
        <button type="button" className="reveal" aria-label={show ? "Hide password" : "Show password"} onClick={() => setShow(!show)}>{show ? <EyeOff size={16} /> : <Eye size={16} />}</button>
      </span>
    </Field>
  );
}

export function Login({ onUser }: { onUser: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<DemoAccounts | null>(null);
  const [code, setCode] = useState("");
  const [needCode, setNeedCode] = useState(false);
  useEffect(() => { void accounts.demo().then(setDemo); }, []);
  const signIn = async (u: string, p: string, c?: string) => {
    setBusy(true);
    setError(null);
    try { onUser(await accounts.login(u, p, c)); }
    catch (err) {
      if (err instanceof TwoStepNeeded) { setUsername(u); setPassword(p); setNeedCode(true); setError(null); }
      else setError(msg(err));
    } finally { setBusy(false); }
  };
  const submit = (e: FormEvent) => { e.preventDefault(); void signIn(username, password, needCode ? code : undefined); };
  return (
    <main className="signin">
      <section className="signin-brand">
        <div className="brand"><span className="logo"><BadgeCheck size={22} aria-hidden /></span><div><strong>EnviroSense</strong><span>Damage assessment decision support</span></div></div>
        <h1>From imagery to a reviewed, accountable damage assessment.</h1>
        <ul>
          <li><ShieldCheck size={20} aria-hidden /><div><strong>Two people for every release</strong><span>An analyst proposes, a different officer confirms.</span></div></li>
          <li><Users size={20} aria-hidden /><div><strong>Your unit's work only</strong><span>Each team sees its own area and the units below it.</span></div></li>
          <li><ScrollText size={20} aria-hidden /><div><strong>Every action on the record</strong><span>A tamper-evident audit log names who did what, and when.</span></div></li>
        </ul>
      </section>
      <section className="signin-form">
        <form onSubmit={submit}>
          <h2>Sign in</h2>
          <p className="hint">Use the account your unit's administrator created for you.</p>
          {error && <Notice tone="error">{error}</Notice>}
          <Field label="Username" wide><input type="text" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} /></Field>
          <Secret label="Password" autoComplete="current-password" value={password} onChange={setPassword} />
          {needCode && (
            <Field label="Code from your authenticator app" hint="Six digits; a new one every 30 seconds." wide>
              <input type="text" inputMode="numeric" autoComplete="one-time-code" autoFocus maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
            </Field>
          )}
          <Button variant="primary" type="submit" disabled={busy || !username || !password || (needCode && code.length !== 6)}>{busy ? "Signing in…" : "Sign in"}</Button>
          <p className="hint center">Sessions end when you sign out or an administrator disables the account.</p>
          {demo && (
            <div className="demo-accounts">
              <div className="demo-head"><strong>Demo accounts</strong><span>Password for all: <code>{demo.password}</code></span></div>
              <ul>
                {demo.accounts.map((a) => (
                  <li key={a.username}>
                    <button type="button" disabled={busy} onClick={() => void signIn(a.username, demo.password)}>
                      <Avatar name={a.name} size={28} />
                      <span><strong>{a.username}</strong><small>{a.role_label} · {a.unit}</small></span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </form>
      </section>
    </main>
  );
}

export function ChangePassword({ user, forced, onDone, onCancel }: { user: User; forced?: boolean; onDone: () => void; onCancel?: () => void }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (next !== again) { setError("The two new passwords differ."); return; }
    setBusy(true);
    setError(null);
    try { await accounts.changePassword(current, next); onDone(); } catch (err) { setError(msg(err)); } finally { setBusy(false); }
  };
  const strong = next.length >= 10;
  const form = (
    <form className="auth-card" onSubmit={submit}>
      <span className="logo"><KeyRound size={20} aria-hidden /></span>
      <h2>{forced ? "Choose your password" : "Change password"}</h2>
      {forced && <p className="hint">{user.name}, an administrator set your first password. Choose your own before you continue.</p>}
      {error && <Notice tone="error">{error}</Notice>}
      <Secret label={forced ? "Temporary password" : "Current password"} autoComplete="current-password" value={current} onChange={setCurrent} autoFocus />
      <Secret label="New password" autoComplete="new-password" value={next} onChange={setNext} hint={<span className={strong ? "ok" : ""}>{strong ? "Long enough." : "At least 10 characters."}</span>} />
      <Secret label="New password again" autoComplete="new-password" value={again} onChange={setAgain} />
      <div className="btn-row end">
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
        <Button variant="primary" type="submit" disabled={busy || !current || !strong}>Save password</Button>
      </div>
    </form>
  );
  return forced ? <main className="auth-page">{form}</main> : <div className="auth-overlay">{form}</div>;
}

/** Two-step sign-in: a code from an authenticator app on top of the password (expected for administrators and approving officers). */
function TwoStepSetup({ user, onClose, onUser }: { user: User; onClose: () => void; onUser: (u: User) => void }) {
  const [setup, setSetup] = useState<{ secret: string; uri: string } | null>(null);
  const [code, setCode] = useState(""), [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<User>) => { setError(null); try { onUser(await fn()); onClose(); } catch (e) { setError(msg(e)); } };
  return (
    <Modal open title="Two-step sign-in" subtitle={user.two_step ? "On: every sign-in asks for a code from your authenticator app." : "Add a code from an authenticator app to your password."} onClose={onClose}
      footer={<Button onClick={onClose}>Close</Button>}>
      {error && <Notice tone="error">{error}</Notice>}
      {user.two_step ? (
        <>
          <Secret label="Password, to switch it off" autoComplete="current-password" value={password} onChange={setPassword} />
          <Button variant="danger" disabled={!password} onClick={() => void run(() => accounts.twoStepDisable(password))}>Switch off</Button>
        </>
      ) : !setup ? (
        <>
          {user.two_step_expected && <Notice tone="warning">Your role can change or release sensitive things; two-step sign-in is expected for it.</Notice>}
          <p className="hint">You need an authenticator app (Google Authenticator, Microsoft Authenticator, Aegis, 1Password…).</p>
          <Button variant="primary" icon={Smartphone} onClick={() => void accounts.twoStepSetup().then(setSetup).catch((e) => setError(msg(e)))}>Set up</Button>
        </>
      ) : (
        <>
          <p>In the app, add an account and enter this key (or open the link on the phone):</p>
          <div className="secret"><code>{setup.secret.match(/.{1,4}/g)?.join(" ")}</code></div>
          <p className="hint mono-sm" style={{ wordBreak: "break-all" }}>{setup.uri}</p>
          <Field label="Then type the 6-digit code it shows" wide>
            <input type="text" inputMode="numeric" maxLength={6} value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} /></Field>
          <Button variant="primary" disabled={code.length !== 6} onClick={() => void run(() => accounts.twoStepEnable(code))}>Switch on</Button>
        </>
      )}
    </Modal>
  );
}

/** Who is signed in, with the unit and role, and the way out. Shown in every header. */
export function AccountChip({ user, onSignOut, onUser }: { user: User; onSignOut: () => void; onUser: (u: User) => void }) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState(false);
  const [twoStep, setTwoStep] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  return (
    <div className="account" ref={ref}>
      <button className="account-btn" aria-expanded={open} aria-haspopup="menu" onClick={() => setOpen(!open)} title={user.unit_path}>
        <Avatar name={user.name} size={32} />
        <span className="account-text"><span className="account-name">{user.name}</span><span className="account-sub">{user.role_label}</span></span>
        <ChevronDown size={16} aria-hidden />
      </button>
      {open && (
        <div className="account-menu" role="menu">
          <div className="account-who"><strong>{user.name}</strong><span>{user.username}</span><span>{user.unit_path}</span></div>
          <button role="menuitem" onClick={() => { setOpen(false); setPw(true); }}><KeyRound size={16} aria-hidden />Change password</button>
          <button role="menuitem" onClick={() => { setOpen(false); setTwoStep(true); }}><Smartphone size={16} aria-hidden />Two-step sign-in
            {user.two_step ? <Badge tone="green">On</Badge> : user.two_step_expected ? <Badge tone="amber">Expected</Badge> : null}</button>
          <button role="menuitem" onClick={onSignOut}><LogOut size={16} aria-hidden />Sign out</button>
        </div>
      )}
      {pw && <ChangePassword user={user} onDone={() => { setPw(false); void accounts.me().then(onUser); }} onCancel={() => setPw(false)} />}
      {twoStep && <TwoStepSetup user={user} onClose={() => setTwoStep(false)} onUser={onUser} />}
    </div>
  );
}
