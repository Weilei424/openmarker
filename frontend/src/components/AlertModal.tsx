import { useEffect, useRef } from "react";

interface AlertModalProps {
  message: string;
  onClose: () => void;
  title?: string;
}

// A small, self-contained modal for surfacing input-validation messages.
// Used instead of window.alert(), which is unreliable in the Tauri (WebView2)
// packaged app. Rendered with position:fixed so it overlays the whole window
// regardless of where in the tree it is mounted.
export function AlertModal({ message, onClose, title = "Invalid input" }: AlertModalProps) {
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    okRef.current?.focus();
  }, []);

  return (
    <div
      role="alertdialog"
      aria-modal="true"
      aria-label={title}
      style={styles.overlay}
      onKeyDown={(e) => {
        if (e.key === "Escape") onClose();
      }}
    >
      <div style={styles.box}>
        <div style={styles.title}>{title}</div>
        <p style={styles.message}>{message}</p>
        <div style={styles.actions}>
          <button ref={okRef} onClick={onClose} style={styles.okButton}>
            OK
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  overlay: {
    position: "fixed" as const,
    inset: 0,
    background: "rgba(0, 0, 0, 0.45)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
  },
  box: {
    minWidth: 280,
    maxWidth: 420,
    background: "var(--color-surface)",
    color: "var(--color-text)",
    border: "1px solid var(--color-border)",
    borderRadius: 6,
    padding: "16px 18px",
    boxShadow: "0 8px 28px rgba(0, 0, 0, 0.35)",
  },
  title: {
    fontSize: 15,
    fontWeight: 600,
    marginBottom: 8,
  },
  message: {
    fontSize: 14,
    margin: "0 0 16px",
    lineHeight: 1.4,
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
  },
  okButton: {
    padding: "6px 18px",
    fontSize: 14,
    cursor: "pointer",
  },
} as const;
