import { FormEvent, useState } from "react";
import { accounts, User } from "../api";

const msg = (e: unknown) => String(e).replace(/^Error: /, "");

export function Login({ onUser }: { onUser: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try { onUser(await accounts.login(username, password)); } catch (err) { setError(msg(err)); } finally { setBusy(false); }
  };
  return (
    <main className="auth-page">
      <form className="auth-card" onSubmit={submit}>
        <span className="wordmark">EnviroSense</span>
        <h1>Sign in</h1>
        <p className="meta">Damage assessment decision support. Every action is recorded against your account.</p>
        <label className="field-block"><span>Username</span>
          <input type="text" autoComplete="username" autoFocus value={username} onChange={(e) => setUsername(e.target.value)} /></label>
        <label className="field-block"><span>Password</span>
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></label>
        {error && <p className="meta error-text" role="alert">{error}</p>}
        <button className="button primary" disabled={busy || !username || !password}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="meta">Accounts are created by your unit's administrator.</p>
      </form>
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
  const form = (
    <form className="auth-card" onSubmit={submit}>
      <h1>{forced ? "Choose a new password" : "Change password"}</h1>
      {forced && <p className="meta">{user.name}, your password was set by an administrator. Choose your own before you continue.</p>}
      <label className="field-block"><span>{forced ? "Temporary password" : "Current password"}</span>
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></label>
      <label className="field-block"><span>New password (at least 10 characters)</span>
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></label>
      <label className="field-block"><span>New password again</span>
        <input type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></label>
      {error && <p className="meta error-text" role="alert">{error}</p>}
      <div className="btn-row">
        <button className="button primary" disabled={busy || !current || !next}>Save password</button>
        {onCancel && <button type="button" className="button" onClick={onCancel}>Cancel</button>}
      </div>
    </form>
  );
  return forced ? <main className="auth-page">{form}</main> : <div className="auth-overlay">{form}</div>;
}

/** Who is signed in, with the unit and role, and the way out. Shown in every header. */
export function AccountChip({ user, onSignOut, onUser }: { user: User; onSignOut: () => void; onUser: (u: User) => void }) {
  const [open, setOpen] = useState(false);
  const [pw, setPw] = useState(false);
  return (
    <div className="account">
      <button className="account-btn" aria-expanded={open} onClick={() => setOpen(!open)} title={user.unit_path}>
        <span className="account-name">{user.name}</span>
        <span className="account-sub">{user.role_label} · {user.unit_name}</span>
      </button>
      {open && (
        <div className="account-menu" role="menu">
          <p className="meta">Signed in as <strong>{user.username}</strong><br />{user.unit_path}</p>
          <button className="link" role="menuitem" onClick={() => { setOpen(false); setPw(true); }}>Change password</button>
          <button className="link" role="menuitem" onClick={onSignOut}>Sign out</button>
        </div>
      )}
      {pw && <ChangePassword user={user} onDone={() => { setPw(false); void accounts.me().then(onUser); }} onCancel={() => setPw(false)} />}
    </div>
  );
}
