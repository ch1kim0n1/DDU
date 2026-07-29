import {useEffect, useState} from "react";

export type Toast = {
  id: string;
  message: string;
  severity: "error" | "warn" | "info";
};

export function useToastQueue() {
  const [toasts, setToasts] = useState<Toast[]>([]);

  function push(message: string, severity: Toast["severity"] = "error") {
    const id = crypto.randomUUID();
    setToasts((current) => [...current, {id, message, severity}]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 5000);
  }

  function dismiss(id: string) {
    setToasts((current) => current.filter((toast) => toast.id !== id));
  }

  return {toasts, push, dismiss};
}

export function ToastStack({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    // keep for a11y live region updates
  }, [toasts]);

  if (toasts.length === 0) return null;
  return (
    <div className="toast-stack" aria-live="polite">
      {toasts.map((toast) => (
        <div className={`toast-item toast-${toast.severity}`} key={toast.id} role="status">
          <span>{toast.message}</span>
          <button type="button" aria-label="Dismiss" onClick={() => onDismiss(toast.id)}>
            X
          </button>
        </div>
      ))}
    </div>
  );
}
