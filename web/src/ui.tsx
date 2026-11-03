import { ButtonHTMLAttributes, ReactNode, useEffect, useRef } from "react";
import { AlertTriangle, CheckCircle2, Info, LucideIcon, X, XCircle } from "lucide-react";

/** Small set of shared building blocks, so every screen looks and behaves the same. Styles are in styles.css (section "Design system"). */

export type Tone = "neutral" | "blue" | "green" | "amber" | "red" | "violet";

export function Button({ variant = "secondary", size, icon: Icon, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm"; icon?: LucideIcon }) {
  const cls = ["button", variant === "primary" ? "primary" : variant === "ghost" ? "ghost" : variant === "danger" ? "danger" : "", size === "sm" ? "sm" : ""].filter(Boolean).join(" ");
  return <button type="button" {...rest} className={cls}>{Icon && <Icon size={16} aria-hidden />}{children}</button>;
}

export function IconButton({ icon: Icon, label, tone, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { icon: LucideIcon; label: string; tone?: "danger" }) {
  return <button type="button" {...rest} className={`icon-btn ${tone ?? ""}`} aria-label={label} title={label}><Icon size={17} aria-hidden /></button>;
}

export function Badge({ tone = "neutral", dot, icon: Icon, children }: { tone?: Tone; dot?: boolean; icon?: LucideIcon; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{dot && <i className="dot" aria-hidden />}{Icon && <Icon size={12} aria-hidden />}{children}</span>;
}

const PALETTE = ["#DBEAFE:#1E40AF", "#DCFCE7:#166534", "#FEF3C7:#92400E", "#FCE7F3:#9D174D", "#E0E7FF:#3730A3", "#CCFBF1:#115E59", "#FFE4E6:#9F1239", "#EDE9FE:#5B21B6"];

export function Avatar({ name, size = 34 }: { name: string; size?: number }) {
  const initials = name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0].toUpperCase()).join("") || "?";
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const [bg, fg] = PALETTE[h % PALETTE.length].split(":");
  return <span className="avatar" style={{ width: size, height: size, background: bg, color: fg, fontSize: size * 0.38 }} aria-hidden>{initials}</span>;
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="page-head">
      <div><h1>{title}</h1>{subtitle && <p>{subtitle}</p>}</div>
      {actions && <div className="page-actions">{actions}</div>}
    </header>
  );
}

export function Card({ title, subtitle, actions, children, flush }: { title?: ReactNode; subtitle?: ReactNode; actions?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className="card">
      {(title || actions) && (
        <div className="card-head">
          <div>{title && <h2>{title}</h2>}{subtitle && <p>{subtitle}</p>}</div>
          {actions && <div className="card-actions">{actions}</div>}
        </div>
      )}
      <div className={flush ? "card-body flush" : "card-body"}>{children}</div>
    </section>
  );
}

export function Field({ label, hint, children, wide }: { label: string; hint?: ReactNode; children: ReactNode; wide?: boolean }) {
  return <label className={`field${wide ? " wide" : ""}`}><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>;
}

const NOTICE_ICON: Record<string, LucideIcon> = { info: Info, success: CheckCircle2, warning: AlertTriangle, error: XCircle };

export function Notice({ tone = "info", children, onClose }: { tone?: "info" | "success" | "warning" | "error"; children: ReactNode; onClose?: () => void }) {
  const Icon = NOTICE_ICON[tone];
  return (
    <div className={`notice notice-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden /><div>{children}</div>
      {onClose && <IconButton icon={X} label="Dismiss" onClick={onClose} />}
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children?: ReactNode }) {
  return <div className="empty"><span className="empty-icon"><Icon size={22} aria-hidden /></span><strong>{title}</strong>{children && <p>{children}</p>}</div>;
}

/** A dialog on the platform <dialog> element: focus is trapped, Escape closes it, the page behind is inert. */
export function Modal({ open, title, subtitle, onClose, children, footer, width = 520 }:
  { open: boolean; title: string; subtitle?: ReactNode; onClose: () => void; children: ReactNode; footer?: ReactNode; width?: number }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} className="modal" style={{ width: `min(${width}px, calc(100vw - 32px))` }} onClose={onClose} onCancel={onClose}>
      {open && (
        <>
          <header className="modal-head">
            <div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div>
            <IconButton icon={X} label="Close" onClick={onClose} />
          </header>
          <div className="modal-body">{children}</div>
          {footer && <footer className="modal-foot">{footer}</footer>}
        </>
      )}
    </dialog>
  );
}

export const roleTone = (role: string): Tone => ({ admin: "violet", officer: "blue", analyst: "green", auditor: "amber" } as Record<string, Tone>)[role] ?? "neutral";

export function when(utc?: string | null): string {
  if (!utc) return "Never";
  const t = new Date(utc.replace(" ", "T") + "Z");
  const mins = Math.round((Date.now() - t.getTime()) / 60000);
  if (mins < 1) return "Just now";
  if (mins < 60) return `${mins} min ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)} h ago`;
  return t.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
