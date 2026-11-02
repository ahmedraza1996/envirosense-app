import { useEffect, useState } from "react";
import { accounts, User } from "./api";
import { AccountChip, ChangePassword, Login } from "./components/Account";
import AdminShell from "./components/Admin";
import { Workspace } from "./App";

/** Signed-out, first-sign-in and per-role entry. The server decides what each role may do; this only chooses what to show. */
export default function Shell() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  useEffect(() => {
    accounts.me().then(setUser).catch(() => setUser(null));
    const out = () => setUser(null);
    window.addEventListener("auth-expired", out);
    return () => window.removeEventListener("auth-expired", out);
  }, []);
  const signOut = () => { void accounts.logout().finally(() => setUser(null)); };

  if (user === undefined) return <main className="auth-page"><p className="meta">Loading…</p></main>;
  if (user === null) return <Login onUser={setUser} />;
  if (user.must_change_password) return <ChangePassword user={user} forced onDone={() => void accounts.me().then(setUser)} />;
  if (user.role === "analyst" || user.role === "officer") return <Workspace user={user} onUser={setUser} onSignOut={signOut} />;
  return (
    <div className="app admin-app">
      <header className="header">
        <span className="wordmark">EnviroSense</span>
        <nav className="crumbs" aria-label="Location"><span>{user.role === "admin" ? "Administration" : "Audit"}</span></nav>
        <div className="spacer" />
        <AccountChip user={user} onSignOut={signOut} onUser={setUser} />
      </header>
      <AdminShell user={user} tabs={user.role === "admin" ? ["users", "units", "model", "audit"] : ["audit"]} />
    </div>
  );
}
