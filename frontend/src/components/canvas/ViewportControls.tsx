// HTML overlay for zoom/fit controls, positioned over the Konva stage.

interface Props {
  scale: number;
  onFit: () => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
}

export function ViewportControls({ scale, onFit, onZoomIn, onZoomOut }: Props) {
  return (
    <div style={styles.container}>
      <span style={styles.zoomLabel}>{Math.round(scale * 100)}%</span>
      <button style={styles.btn} onClick={onFit} title="Fit all pieces">
        Fit
      </button>
      <button style={styles.btn} onClick={onZoomIn} title="Zoom in">
        +
      </button>
      <button style={styles.btn} onClick={onZoomOut} title="Zoom out">
        −
      </button>
    </div>
  );
}

const styles = {
  container: {
    position: "absolute" as const,
    top: 10,
    right: 10,
    display: "flex",
    alignItems: "center",
    gap: 4,
    background: "rgba(30, 30, 30, 0.85)",
    border: "1px solid rgba(255,255,255,0.1)",
    borderRadius: 4,
    padding: "4px 8px",
    zIndex: 10,
    userSelect: "none" as const,
  },
  zoomLabel: {
    fontSize: 11,
    color: "#aaa",
    minWidth: 36,
    textAlign: "right" as const,
  },
  btn: {
    background: "rgba(255,255,255,0.08)",
    border: "1px solid rgba(255,255,255,0.12)",
    borderRadius: 3,
    color: "#ddd",
    fontSize: 13,
    cursor: "pointer",
    padding: "2px 8px",
    lineHeight: 1.4,
  },
} as const;
