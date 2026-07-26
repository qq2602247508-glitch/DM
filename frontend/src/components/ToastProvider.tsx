import { useCallback, useMemo, useState, type ReactElement, type ReactNode } from "react";

import { ToastContext, type ToastTone } from "../hooks/toastContext";
import { Icon } from "../ui/icons";

type Toast = { id: number; message: string; tone: ToastTone };

const COLORS: Record<ToastTone, string> = {
  success: "border-emerald-700/70 bg-emerald-950/95 text-emerald-200",
  error: "border-red-800/70 bg-red-950/95 text-red-200",
  info: "border-violet-800/70 bg-violet-950/95 text-violet-200",
};

export function ToastProvider({ children }: { children: ReactNode }): ReactElement {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const showToast = useCallback((message: string, tone: ToastTone = "success") => {
    const id = Date.now() + Math.random();
    setToasts((items) => [...items, { id, message, tone }].slice(-4));
    window.setTimeout(() => setToasts((items) => items.filter((item) => item.id !== id)), 3_500);
  }, []);
  const api = useMemo(() => ({ showToast }), [showToast]);
  return (
    <ToastContext.Provider value={api}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed right-4 top-4 z-50 flex w-[min(24rem,calc(100vw-2rem))] flex-col gap-2">
        {toasts.map((toast) => (
          <div className={`pointer-events-auto flex items-start gap-2 rounded-md border px-3 py-2.5 text-sm shadow-panel ${COLORS[toast.tone]}`} key={toast.id} role="status">
            <Icon className="mt-0.5 shrink-0" name={toast.tone === "error" ? "alert" : "check"} size={14} />
            <span className="flex-1">{toast.message}</span>
            <button aria-label="关闭提示" className="text-current opacity-60 hover:opacity-100" onClick={() => setToasts((items) => items.filter((item) => item.id !== toast.id))} type="button">×</button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
