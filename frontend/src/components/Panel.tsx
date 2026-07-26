import type { PropsWithChildren, ReactElement, ReactNode } from "react";

type PanelProps = PropsWithChildren<{
  eyebrow?: string;
  title: string;
  action?: ReactNode;
  className?: string;
  /** Remove the header divider padding so children control their own spacing. */
  flush?: boolean;
}>;

export function Panel({
  eyebrow,
  title,
  action,
  className = "",
  flush = false,
  children,
}: PanelProps): ReactElement {
  return (
    <section
      className={`flex min-h-0 flex-col rounded-lg border border-ink-700/80 bg-ink-900/90 shadow-panel ${className}`}
    >
      <div className="flex items-center justify-between gap-3 border-b border-ink-700/70 px-4 py-3">
        <div className="min-w-0">
          {eyebrow ? (
            <p className="m-0 text-2xs font-semibold uppercase tracking-[0.22em] text-ember-400/90">
              {eyebrow}
            </p>
          ) : null}
          <h2 className="m-0 mt-0.5 truncate font-display text-base font-normal text-parchment-100">
            {title}
          </h2>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className={`min-h-0 flex-1 ${flush ? "" : "px-4 py-3"}`}>{children}</div>
    </section>
  );
}
