interface BottomPanelProps {
  markerLengthMm: number | null;
  utilizationPct: number | null;
  durationMs: number | null;
  overflow: boolean;
}

export function formatDuration(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const mm = Math.floor(totalSeconds / 60);
  const ss = totalSeconds % 60;
  return `${String(mm).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
}

export function BottomPanel({
  markerLengthMm,
  utilizationPct,
  durationMs,
  overflow,
}: BottomPanelProps) {
  if (markerLengthMm === null || utilizationPct === null || durationMs === null) {
    return (
      <div style={styles.root}>
        <span style={styles.placeholder}>No layout yet. Click Auto Layout.</span>
      </div>
    );
  }

  const utilColor =
    utilizationPct >= 75 ? "var(--color-success)"
    : utilizationPct >= 50 ? "var(--color-warning)"
    : "var(--color-text)";

  return (
    <div style={styles.root}>
      <div style={styles.item}>
        <span style={styles.label}>Length:</span>
        <span style={styles.value}>{Math.round(markerLengthMm)} mm</span>
      </div>
      <div style={styles.item}>
        <span style={styles.label}>Util:</span>
        <span style={{ ...styles.value, color: utilColor }}>
          {overflow ? "—" : `${utilizationPct.toFixed(1)}%`}
        </span>
      </div>
      <div style={styles.item}>
        <span style={styles.label}>⏱</span>
        <span style={styles.value}>{formatDuration(durationMs)}</span>
      </div>
      {overflow && (
        <span style={styles.warn}>Pieces overflow fabric.</span>
      )}
    </div>
  );
}

const styles = {
  root: {
    height: 32,
    background: "var(--color-surface)",
    borderTop: "1px solid var(--color-border)",
    display: "flex",
    alignItems: "center",
    gap: 24,
    padding: "0 16px",
    fontSize: 12,
    color: "var(--color-text)",
    flexShrink: 0,
  },
  item: {
    display: "flex",
    alignItems: "center",
    gap: 6,
  },
  label: {
    color: "var(--color-text-muted)",
  },
  value: {
    fontWeight: 600 as const,
  },
  warn: {
    marginLeft: "auto",
    color: "var(--color-warning)",
  },
  placeholder: {
    color: "var(--color-text-muted)",
  },
} as const;
