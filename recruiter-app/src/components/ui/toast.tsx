"use client";

import React, { createContext, useContext, useState, useCallback } from "react";
import { X, CheckCircle, AlertCircle, Info } from "lucide-react";

type ToastType = "success" | "error" | "info";

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextType | null>(null);

// Collision-free id. Prefer crypto.randomUUID(); fall back for the rare
// runtime that lacks it (older Safari / non-secure context) so toasts never
// share an id (which would make removeToast drop the wrong one).
function createToastId(): string {
  const cryptoObj =
    typeof globalThis !== "undefined"
      ? (globalThis.crypto as Crypto | undefined)
      : undefined;
  if (cryptoObj?.randomUUID) {
    return `toast-${cryptoObj.randomUUID()}`;
  }
  return `toast-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

export function useToast() {
  const context = useContext(ToastContext);
  if (!context) {
    throw new Error("useToast must be used within a ToastProvider");
  }
  return context;
}

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = useCallback((message: string, type: ToastType = "info") => {
    const id = createToastId();
    setToasts((prev) => [...prev, { id, message, type }]);

    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 5000);
  }, []);

  const removeToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      {/* Live region: screen readers announce toasts as they mount. Errors are
          announced assertively (interrupt), everything else politely. */}
      <div
        id="toast-region"
        role="status"
        aria-live="polite"
        aria-relevant="additions"
        className="fixed top-4 right-4 z-[100] flex flex-col gap-3 max-w-sm"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            id={toast.id}
            data-slot="toast-item"
            data-toast-id={toast.id}
            role="status"
            aria-live={toast.type === "error" ? "assertive" : "polite"}
            className={`flex items-start gap-3 px-4 py-3 rounded-lg shadow-lg border animate-in slide-in-from-right-5 fade-in duration-300 ${
              toast.type === "success"
                ? "bg-[#ECFDF5] border-[#A7F3D0] text-[#047857]"
                : toast.type === "error"
                ? "bg-red-50 border-red-200 text-red-800"
                : "bg-blue-50 border-blue-200 text-blue-800"
            }`}
          >
            <div className="flex-shrink-0 mt-0.5">
              {toast.type === "success" && <CheckCircle className="w-5 h-5" />}
              {toast.type === "error" && <AlertCircle className="w-5 h-5" />}
              {toast.type === "info" && <Info className="w-5 h-5" />}
            </div>
            <p className="flex-1 text-sm font-medium">{toast.message}</p>
            <button
              type="button"
              id={`${toast.id}-dismiss`}
              aria-label="Dismiss notification"
              onClick={() => removeToast(toast.id)}
              className="flex-shrink-0 p-1 rounded hover:bg-black/10 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}
