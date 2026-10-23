import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Check } from "../api/types";

export function cx(...parts: (string | false | null | undefined)[]) {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "ghost" | "danger";

export function Button({ variant = "secondary", size = "md", className, children, ...rest }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" | "lg" }) {
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-2 font-medium transition-colors select-none",
        "disabled:opacity-40 disabled:cursor-not-allowed rounded-[var(--radius-control)]",
        size === "sm" && "h-9 px-3 text-sm",
        size === "md" && "h-11 px-4 text-[15px]",
        size === "lg" && "h-14 px-6 text-base",
        variant === "primary" && "bg-accent text-accent-ink hover:brightness-105 active:brightness-95",
        variant === "secondary" && "bg-ink-800 text-ink-100 hover:bg-ink-700 border border-ink-700",
        variant === "ghost" && "text-ink-300 hover:text-ink-100 hover:bg-ink-800",
        variant === "danger" && "text-bad hover:bg-bad/10 border border-bad/30",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cx("bg-ink-850 border border-ink-700/70 rounded-[var(--radius-card)]", className)}>{children}</div>
  );
}

export function Pill({ tone = "neutral", children }: { tone?: "neutral" | "ok" | "warn" | "bad" | "accent"; children: ReactNode }) {
  return (
    <span className={cx(
      "inline-flex shrink-0 items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-xs font-medium",
      tone === "neutral" && "bg-ink-800 text-ink-300",
      tone === "ok" && "bg-ok/10 text-ok",
      tone === "warn" && "bg-warn/10 text-warn",
      tone === "bad" && "bg-bad/10 text-bad",
      tone === "accent" && "bg-accent/15 text-accent",
    )}>{children}</span>
  );
}

export function Spinner({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={cx("h-4 w-4 animate-spin", className)} aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" fill="none" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" fill="none" strokeLinecap="round" />
    </svg>
  );
}

const ICON: Record<Check["level"], string> = { ok: "✓", warn: "!", block: "×" };

/** Clip checks read as guidance: what we found, and what to do about it. */
export function CheckList({ checks }: { checks: Check[] }) {
  return (
    <ul className="space-y-2">
      {checks.map((c) => (
        <li key={c.id} className="flex gap-3 text-sm">
          <span className={cx(
            "mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full text-[11px] font-bold",
            c.level === "ok" && "bg-ok/15 text-ok",
            c.level === "warn" && "bg-warn/15 text-warn",
            c.level === "block" && "bg-bad/15 text-bad",
          )} aria-label={c.level}>{ICON[c.level]}</span>
          <span>
            <span className="text-ink-100">{c.message}</span>
            {c.hint && <span className="block text-ink-500">{c.hint}</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

export function SectionTitle({ step, title, hint }: { step?: string; title: string; hint?: string }) {
  return (
    <div className="mb-4">
      {step && <div className="mb-1 text-xs font-semibold uppercase tracking-[0.14em] text-ink-500">{step}</div>}
      <h2 className="text-xl font-semibold tracking-tight text-ink-100">{title}</h2>
      {hint && <p className="mt-1 text-sm text-ink-300">{hint}</p>}
    </div>
  );
}

export function formatEta(seconds?: number): string {
  if (seconds === undefined) return "";
  if (seconds < 60) return "under a minute";
  const m = Math.round(seconds / 60);
  return `about ${m} minute${m === 1 ? "" : "s"}`;
}

/** CSS aspect-ratio for a job's player box: its real delivered shape, portrait until it is known. */
export function aspectOf(aspect?: [number, number]): React.CSSProperties {
  return { aspectRatio: aspect ? `${aspect[0]} / ${aspect[1]}` : "9 / 16" };
}
