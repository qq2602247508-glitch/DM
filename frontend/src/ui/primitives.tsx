import type { ButtonHTMLAttributes, ReactElement, ReactNode } from "react";

import { describeError } from "./errors";
import { Icon, type IconName } from "./icons";
import {
  badgeBase,
  btnAi,
  btnDanger,
  btnGhost,
  btnPrimary,
  toneClasses,
  type Tone,
} from "./styles";

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------

export function Badge({
  tone = "neutral",
  icon,
  children,
}: {
  tone?: Tone;
  icon?: IconName;
  children: ReactNode;
}): ReactElement {
  return (
    <span className={`${badgeBase} ${toneClasses[tone]}`}>
      {icon ? <Icon name={icon} size={11} /> : null}
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------

const VARIANT_CLASSES = {
  primary: btnPrimary,
  ghost: btnGhost,
  danger: btnDanger,
  ai: btnAi,
} as const;

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof VARIANT_CLASSES;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: IconName;
};

export function Button({
  variant = "ghost",
  size = "md",
  loading = false,
  icon,
  className = "",
  children,
  disabled,
  type = "button",
  ...rest
}: ButtonProps): ReactElement {
  const sizeCls = size === "sm" ? "px-2 py-1 text-xs" : "";
  return (
    <button
      className={`${VARIANT_CLASSES[variant]} ${sizeCls} ${className}`}
      disabled={disabled === true || loading}
      type={type}
      {...rest}
    >
      {loading ? <Spinner size={13} /> : icon ? <Icon name={icon} size={14} /> : null}
      {children}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Spinner & skeleton
// ---------------------------------------------------------------------------

export function Spinner({ size = 16 }: { size?: number }): ReactElement {
  return (
    <svg
      aria-label="加载中"
      className="animate-spin text-current"
      fill="none"
      height={size}
      role="status"
      viewBox="0 0 24 24"
      width={size}
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path
        className="opacity-90"
        d="M22 12a10 10 0 0 0-10-10"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="4"
      />
    </svg>
  );
}

export function Skeleton({ className = "" }: { className?: string }): ReactElement {
  return <div aria-hidden="true" className={`animate-pulse rounded bg-ink-700/60 ${className}`} />;
}

export function LoadingBlock({ label = "加载中…" }: { label?: string }): ReactElement {
  return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-stone-500">
      <Spinner size={15} />
      {label}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Status dot
// ---------------------------------------------------------------------------

const DOT_COLORS: Record<Tone, string> = {
  ok: "bg-emerald-400",
  warn: "bg-amber-400",
  danger: "bg-red-400",
  ai: "bg-violet-400",
  neutral: "bg-stone-600",
  ember: "bg-ember-400",
};

export function StatusDot({ tone }: { tone: Tone }): ReactElement {
  return <span aria-hidden="true" className={`inline-block size-1.5 rounded-full ${DOT_COLORS[tone]}`} />;
}

// ---------------------------------------------------------------------------
// Empty & error states
// ---------------------------------------------------------------------------

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon?: IconName;
  title: string;
  hint?: string;
  action?: ReactNode;
}): ReactElement {
  return (
    <div className="flex flex-col items-center justify-center gap-2 px-6 py-10 text-center">
      {icon ? <Icon className="text-stone-600" name={icon} size={22} /> : null}
      <p className="m-0 text-sm text-stone-400">{title}</p>
      {hint ? <p className="m-0 max-w-md text-xs leading-5 text-stone-600">{hint}</p> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}): ReactElement {
  const described = describeError(error);
  return (
    <div className="rounded-md border border-red-900/60 bg-red-950/30 px-4 py-3" role="alert">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-2.5">
          <Icon className="mt-0.5 shrink-0 text-red-400" name="alert" size={15} />
          <div>
            <p className="m-0 text-sm font-medium text-red-300">{described.title}</p>
            <p className="mb-0 mt-1 text-xs leading-5 text-stone-400">{described.message}</p>
            {described.guidance ? (
              <p className="mb-0 mt-2 border-l-2 border-amber-700/60 pl-2.5 text-xs leading-5 text-amber-200/90">
                {described.guidance}
              </p>
            ) : null}
          </div>
        </div>
        {onRetry ? (
          <Button icon="refresh" onClick={onRetry} size="sm" variant="ghost">
            重试
          </Button>
        ) : null}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Small layout helpers
// ---------------------------------------------------------------------------

export function SectionLabel({ children }: { children: ReactNode }): ReactElement {
  return (
    <p className="m-0 text-2xs font-semibold uppercase tracking-[0.18em] text-stone-500">
      {children}
    </p>
  );
}

export function KeyValue({ k, v }: { k: ReactNode; v: ReactNode }): ReactElement {
  return (
    <div className="flex items-baseline justify-between gap-3 py-1">
      <dt className="shrink-0 text-xs text-stone-500">{k}</dt>
      <dd className="m-0 text-right text-sm text-parchment-100">{v}</dd>
    </div>
  );
}

export function Tabs({
  tabs,
  active,
  onChange,
}: {
  tabs: { id: string; label: string; count?: number }[];
  active: string;
  onChange: (id: string) => void;
}): ReactElement {
  return (
    <div className="flex gap-1 border-b border-ink-700" role="tablist">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            aria-selected={selected}
            className={`relative px-3 py-2 text-sm transition-colors ${
              selected ? "text-ember-300" : "text-stone-500 hover:text-stone-300"
            }`}
            key={tab.id}
            onClick={() => onChange(tab.id)}
            role="tab"
            type="button"
          >
            {tab.label}
            {tab.count !== undefined ? (
              <span
                className={`ml-1.5 rounded-full px-1.5 py-0.5 text-2xs ${
                  selected ? "bg-ember-500/20 text-ember-300" : "bg-ink-700 text-stone-500"
                }`}
              >
                {tab.count}
              </span>
            ) : null}
            {selected ? (
              <span className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-ember-400" />
            ) : null}
          </button>
        );
      })}
    </div>
  );
}
