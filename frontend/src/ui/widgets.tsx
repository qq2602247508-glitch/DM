import { useState, type ReactElement, type ReactNode } from "react";

import { clamp } from "./format";
import { Icon } from "./icons";
import { Button } from "./primitives";
import { badgeBase, toneClasses } from "./styles";

// ---------------------------------------------------------------------------
// DM-only & AI tags — the two trust markers used across the whole console.
// ---------------------------------------------------------------------------

export function DmOnlyTag(): ReactElement {
  return (
    <span className={`${badgeBase} ${toneClasses.warn}`} title="仅 DM 可见，玩家不可见">
      <Icon name="lock" size={11} />
      DM 私密
    </span>
  );
}

export function AiTag({ children = "AI 建议" }: { children?: ReactNode }): ReactElement {
  return (
    <span className={`${badgeBase} ${toneClasses.ai}`} title="由本地模型生成，仅供参考">
      <Icon name="sparkle" size={11} />
      {children}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Copy button with feedback
// ---------------------------------------------------------------------------

export function CopyButton({
  text,
  label = "复制",
  className = "",
}: {
  text: string;
  label?: string;
  className?: string;
}): ReactElement {
  const [copied, setCopied] = useState(false);

  const copy = () => {
    const done = () => {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
    } else {
      fallbackCopy(text, done);
    }
  };

  return (
    <Button className={className} icon={copied ? "check" : "copy"} onClick={copy} size="sm">
      {copied ? "已复制" : label}
    </Button>
  );
}

function fallbackCopy(text: string, done: () => void): void {
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  try {
    document.execCommand("copy");
    done();
  } finally {
    document.body.removeChild(area);
  }
}

// ---------------------------------------------------------------------------
// HP bar
// ---------------------------------------------------------------------------

export function HpBar({ hp, maxHp }: { hp: number; maxHp: number }): ReactElement {
  const ratio = maxHp > 0 ? clamp(hp / maxHp, 0, 1) : 0;
  const color =
    ratio > 0.5 ? "bg-emerald-500" : ratio > 0.25 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div
        aria-label={`HP ${hp} / ${maxHp}`}
        aria-valuemax={maxHp}
        aria-valuenow={hp}
        className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700"
        role="progressbar"
      >
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${ratio * 100}%` }} />
      </div>
      <span className="shrink-0 font-mono text-2xs text-stone-400">
        {hp}/{maxHp}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Secret block — DM-private field hidden until explicitly revealed
// ---------------------------------------------------------------------------

export function SecretBlock({
  label,
  value,
}: {
  label: string;
  value: string | null;
}): ReactElement {
  const [revealed, setRevealed] = useState(false);
  return (
    <div className="rounded-md border border-dashed border-amber-800/60 bg-amber-950/20 px-3 py-2.5">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-amber-300/90">
          <Icon name="lock" size={12} />
          {label}
        </span>
        <button
          className="flex items-center gap-1 text-2xs text-stone-500 transition-colors hover:text-stone-300"
          onClick={() => setRevealed((v) => !v)}
          type="button"
        >
          <Icon name={revealed ? "eye-off" : "eye"} size={12} />
          {revealed ? "隐藏" : "显示"}
        </button>
      </div>
      {revealed ? (
        <p className="prose-block mb-0 mt-2 text-sm text-parchment-100">
          {value?.trim() ? value : "（未填写）"}
        </p>
      ) : (
        <p className="m-0 mt-1 text-2xs italic text-stone-600">已隐藏 — 玩家不可见内容</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Form field wrapper with inline error
// ---------------------------------------------------------------------------

export function Field({
  label,
  htmlFor,
  error,
  hint,
  required = false,
  children,
}: {
  label: string;
  htmlFor?: string;
  error?: string | undefined;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}): ReactElement {
  return (
    <div>
      <label className="mb-1.5 flex items-baseline gap-1 text-xs font-medium text-stone-400" htmlFor={htmlFor}>
        {label}
        {required ? <span className="text-red-400">*</span> : null}
      </label>
      {children}
      {error ? (
        <p className="mb-0 mt-1.5 flex items-center gap-1 text-2xs text-red-400" role="alert">
          <Icon name="alert" size={11} />
          {error}
        </p>
      ) : hint ? (
        <p className="mb-0 mt-1.5 text-2xs text-stone-600">{hint}</p>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Confirm dialog — used for every destructive action (double confirmation)
// ---------------------------------------------------------------------------

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel = "确认",
  loading = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  loading?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}): ReactElement | null {
  if (!open) {
    return null;
  }
  return (
    <div
      aria-modal="true"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 p-4 backdrop-blur-sm"
      onClick={onCancel}
      role="dialog"
    >
      <div
        className="w-full max-w-md rounded-lg border border-ink-600 bg-ink-900 shadow-panel"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-center gap-2 border-b border-ink-700 px-5 py-3.5">
          <Icon className="text-red-400" name="alert" size={16} />
          <h3 className="m-0 font-display text-base text-parchment-100">{title}</h3>
        </div>
        <div className="px-5 py-4 text-sm leading-6 text-stone-300">{body}</div>
        <div className="flex justify-end gap-2 border-t border-ink-700 px-5 py-3.5">
          <Button disabled={loading} onClick={onCancel}>
            取消
          </Button>
          <Button loading={loading} onClick={onConfirm} variant="danger">
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  );
}
