import { useEffect, useState } from "react";
import { accounts, User } from "./api";
import { ChangePassword, Login } from "./components/Account";
import AppShell, { Section, sectionsFor } from "./components/AppShell";
import { Approvals, AuditView, ModelApproval, Roles, Units, Users } from "./components/Admin";
import { Workspace } from "./App";

/** Signed-out, first-sign-in and the one application frame for every role. The server decides what each role may do; this only
 *  chooses which sections to show. */
export default function Shell() {
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [section, setSection] = useState<Section | null>(null);
  const [visit, setVisit] = useState(0);            // a click on the current section (or its crumb) goes back to that section's start
  const [crumb, setCrumb] = useState<string | null>(null);
  useEffect(() => {
    accounts.me().then(setUser).catch(() => setUser(null));
    const out = () => setUser(null);
    window.addEventListener("auth-expired", out);
    return () => window.removeEventListener("auth-expired", out);
  }, []);
  const signOut = () => { void accounts.logout().finally(() => { setUser(null); setSection(null); }); };

  if (user === undefined) return <main className="auth-page"><p className="hint">Loading…</p></main>;
  if (user === null) return <Login onUser={setUser} />;
  if (user.must_change_password) return <ChangePassword user={user} forced onDone={() => void accounts.me().then(setUser)} />;
  const allowed = sectionsFor(user).map((n) => n.id);
  const current = section && allowed.includes(section) ? section : allowed[0];
  if (!current) return <main className="auth-page"><p className="hint">This account has no sections. Ask an administrator for a role.</p></main>;
  const go = (s: Section) => { setSection(s); setVisit((v) => v + 1); setCrumb(null); };
  const work = current === "assessments" || current === "events" || current === "benchmark";

  return (
    <AppShell user={user} onUser={setUser} onSignOut={signOut} section={current} onSection={go} crumb={crumb}>
      {work && <Workspace user={user} section={current} visit={visit} onSection={go} onCrumb={setCrumb} />}
      {current === "users" && <Users me={user} />}
      {current === "units" && <Units />}
      {current === "roles" && <Roles />}
      {current === "approvals" && <Approvals me={user} onChange={() => undefined} />}
      {current === "model" && <ModelApproval />}
      {current === "audit" && <AuditView />}
    </AppShell>
  );
}
