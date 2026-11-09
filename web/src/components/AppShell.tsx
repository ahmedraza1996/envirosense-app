import { ReactNode, useCallback, useEffect, useState } from "react";
import {
  BadgeCheck, ClipboardCheck, Cpu, FlaskConical, Globe2, Layers, LucideIcon, Network, ScrollText, ShieldCheck, Users as UsersIcon,
} from "lucide-react";
import { accounts, can, User } from "../api";
import { AccountChip } from "./Account";

/** One frame for every role: the same navigation, top bar and account menu. Each role sees only the sections it may use;
 *  the server still decides what each request may do. */

export type Section = "assessments" | "events" | "benchmark" | "approvals" | "model" | "audit" | "users" | "units" | "roles";

interface NavItem { id: Section; label: string; icon: LucideIcon; group: string; show: (u: User) => boolean; full?: boolean }

const admin = (u: User) => can(u, "users");
export const NAV: NavItem[] = [
  { id: "assessments", label: "Assessments", icon: Layers, group: "Damage assessment", show: (u) => can(u, "view"), full: true },
  { id: "events", label: "Events", icon: Globe2, group: "Damage assessment", show: (u) => can(u, "view"), full: true },
  { id: "benchmark", label: "Model check", icon: FlaskConical, group: "Damage assessment", show: (u) => can(u, "view"), full: true },
  { id: "approvals", label: "Approvals", icon: ClipboardCheck, group: "Governance", show: (u) => admin(u) || can(u, "model_approve") },
  { id: "model", label: "Approved model", icon: Cpu, group: "Governance", show: (u) => admin(u) || can(u, "model_approve") },
  { id: "audit", label: "Audit log", icon: ScrollText, group: "Governance", show: (u) => admin(u) || can(u, "audit") },
  { id: "users", label: "Users", icon: UsersIcon, group: "Access", show: admin },
  { id: "units", label: "Units", icon: Network, group: "Access", show: admin },
  { id: "roles", label: "Roles", icon: ShieldCheck, group: "Access", show: admin },
];

export function sectionsFor(u: User): NavItem[] { return NAV.filter((n) => n.show(u)); }

export default function AppShell({ user, onUser, onSignOut, section, onSection, crumb, children }: {
  user: User; onUser: (u: User) => void; onSignOut: () => void; section: Section; onSection: (s: Section) => void;
  crumb?: ReactNode; children: ReactNode;
}) {
  const items = sectionsFor(user);
  const groups = [...new Set(items.map((n) => n.group))];
  const current = items.find((n) => n.id === section);
  const [waiting, setWaiting] = useState(0);
  const refresh = useCallback(() => {
    if (items.some((n) => n.id === "approvals")) accounts.approvals("pending").then((r) => setWaiting(r.filter((x) => x.can_decide).length)).catch(() => undefined);
  }, [items.length]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(refresh, [refresh, section]);

  return (
    <div className="console">
      <aside className="nav">
        <div className="brand"><span className="logo"><BadgeCheck size={20} aria-hidden /></span><div><strong>EnviroSense</strong><span>Damage assessment</span></div></div>
        <nav aria-label="Sections">
          {groups.map((g) => (
            <div key={g} className="nav-group">
              <span className="nav-title">{g}</span>
              {items.filter((n) => n.group === g).map((n) => (
                <button key={n.id} className="nav-item" aria-current={section === n.id ? "page" : undefined} onClick={() => onSection(n.id)}>
                  <n.icon size={18} aria-hidden /><span>{n.label}</span>
                  {n.id === "approvals" && waiting > 0 && <span className="nav-badge" aria-label={`${waiting} waiting`}>{waiting}</span>}
                </button>
              ))}
            </div>
          ))}
        </nav>
        <div className="nav-foot"><span>Decision support only: every alert is a draft until a person confirms it.</span></div>
      </aside>
      <div className="console-main">
        <div className="topbar">
          <nav className="crumbs" aria-label="Location">
            <span>{current?.group}</span><span className="slash">/</span>
            {crumb ? <><button className="crumb-link" onClick={() => onSection(section)}>{current?.label}</button><span className="slash">/</span>{crumb}</> : <span>{current?.label}</span>}
          </nav>
          <div className="spacer" />
          <AccountChip user={user} onSignOut={onSignOut} onUser={onUser} />
        </div>
        {current?.full ? <main className="work">{children}</main> : <main className="page"><div className="page-inner">{children}</div></main>}
      </div>
    </div>
  );
}
