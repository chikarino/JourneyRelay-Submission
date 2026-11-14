// Shared UI pieces: button styles, status labels and line icons.
// Visual rules (REDESIGN.md §2): flat white panels with hairline dividers,
// rectangular buttons, status as a dot + text — no shadowed cards or pills.

import type { TaskStatus } from "./api";

const btnBase =
  "inline-flex min-h-12 items-center justify-center gap-2 px-5 text-base font-semibold " +
  "disabled:cursor-not-allowed disabled:border-line disabled:bg-line disabled:text-ink-2";

export const btn = {
  primary: `${btnBase} bg-cx-green text-white hover:bg-cx-green-dark`,
  secondary: `${btnBase} border border-cx-jade bg-white text-cx-jade hover:bg-cx-jade-95`,
  quiet: `${btnBase} border border-line-strong bg-white text-ink hover:bg-paper-light`,
  danger: `${btnBase} border border-error bg-white text-error hover:bg-error-bg`,
  text: "min-h-11 px-1 font-semibold text-cx-jade underline underline-offset-4 hover:text-cx-jade-dark",
};

const DOT: Record<TaskStatus, string> = {
  pending: "bg-line-strong",
  received: "bg-reminder",
  done: "bg-cx-jade",
  amended: "bg-cx-gold",
  flagged: "bg-error",
  cancelled: "bg-line",
  notified: "bg-cx-jade-90",
};

const TEXT: Record<TaskStatus, string> = {
  pending: "text-ink-2",
  received: "text-reminder",
  done: "text-cx-jade-dark",
  amended: "text-cx-gold",
  flagged: "text-error",
  cancelled: "text-ink-3 line-through",
  notified: "text-ink-2",
};

export function StatusDot({ status }: { status: TaskStatus }) {
  return <span aria-hidden="true" className={`inline-block size-2 shrink-0 rounded-full ${DOT[status]}`} />;
}

export function StatusLabel({ status, children }: { status: TaskStatus; children: React.ReactNode }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-sm font-semibold ${TEXT[status]}`}>
      <StatusDot status={status} />
      {children}
    </span>
  );
}

function Icon({ d, className = "size-5" }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.75} strokeLinecap="round"
      strokeLinejoin="round" aria-hidden="true" className={className}>
      <path d={d} />
    </svg>
  );
}

export const ChevronLeft = (p: { className?: string }) => <Icon d="M15 18l-6-6 6-6" {...p} />;
export const ChevronRight = (p: { className?: string }) => <Icon d="M9 6l6 6-6 6" {...p} />;
export const Close = (p: { className?: string }) => <Icon d="M6 6l12 12M18 6L6 18" {...p} />;
export const ArrowRight = (p: { className?: string }) => <Icon d="M4 12h16M14 6l6 6-6 6" {...p} />;
export const Mic = (p: { className?: string }) => (
  <Icon d="M12 3a3 3 0 0 1 3 3v6a3 3 0 1 1-6 0V6a3 3 0 0 1 3-3zM5 11a7 7 0 0 0 14 0M12 18v3" {...p} />
);
export const Speaker = (p: { className?: string }) => (
  <Icon d="M4 9v6h4l5 4V5L8 9H4zM16 9a4 4 0 0 1 0 6" {...p} />
);
