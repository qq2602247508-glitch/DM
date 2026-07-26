import { createContext, useContext } from "react";

export type ToastTone = "success" | "error" | "info";
export type ToastApi = {
  showToast: (message: string, tone?: ToastTone) => void;
};

export const ToastContext = createContext<ToastApi | null>(null);

export function useToast(): ToastApi {
  const value = useContext(ToastContext);
  if (!value) {
    throw new Error("useToast must be used inside ToastProvider");
  }
  return value;
}
