import { useEffect, useState } from "react";
import { accounts, can, User } from "./api";
import { ChangePassword, Login } from "./components/Account";
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

  if (user === undefined) return <main className="auth-page"><p className="hint">Loading…</p></main>;
  if (user === null) return <Login onUser={setUser} />;
  if (user.must_change_password) return <ChangePassword user={user} forced onDone={() => void accounts.me().then(setUser)} />;
  if (can(user, "view")) return <Workspace user={user} onUser={setUser} onSignOut={signOut} />;
  return <AdminShell user={user} onUser={setUser} onSignOut={signOut} tabs={can(user, "users") ? ["users", "units", "roles", "approvals", "model", "audit"] : ["audit"]} />;
}
