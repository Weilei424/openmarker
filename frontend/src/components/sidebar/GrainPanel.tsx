import type { GrainMode } from "../../types/engine";

interface GrainPanelProps {
  grainMode: GrainMode;
  showGrainline: boolean;
  onGrainModeChange: (mode: GrainMode) => void;
  onShowGrainlineChange: (show: boolean) => void;
}

const GRAIN_MODE_LABELS: Record<GrainMode, string> = {
  single: "Single direction",
  bi: "Bi-directional",
};

export function GrainPanel({
  grainMode,
  showGrainline,
  onGrainModeChange,
  onShowGrainlineChange,
}: GrainPanelProps) {
  return (
    <div>
      <div>
        <div style={styles.label}>Grain Mode</div>
        <div style={styles.hint}>Fabric grain runs top → bottom</div>
        {(["single", "bi"] as const).map((mode) => (
          <label key={mode} style={styles.radioRow}>
            <input
              type="radio"
              name="grain-mode"
              checked={grainMode === mode}
              onChange={() => onGrainModeChange(mode)}
            />
            <span style={{ fontSize: 14 }}>{GRAIN_MODE_LABELS[mode]}</span>
          </label>
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <label style={styles.checkRow}>
          <input
            type="checkbox"
            checked={showGrainline}
            onChange={(e) => onShowGrainlineChange(e.target.checked)}
          />
          <span style={{ fontSize: 14 }}>Show grainline</span>
        </label>
      </div>
    </div>
  );
}

const styles = {
  label: {
    fontSize: 13,
    fontWeight: 600 as const,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
    marginBottom: 4,
  },
  hint: {
    fontSize: 13,
    color: "var(--color-text-muted)",
    marginBottom: 4,
    fontStyle: "italic" as const,
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  checkRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    cursor: "pointer",
  },
} as const;
