import type { GrainMode } from "../../types/engine";

interface GrainPanelProps {
  grainMode: GrainMode;
  fastMode: boolean;
  onGrainModeChange: (mode: GrainMode) => void;
  onFastModeChange: (enabled: boolean) => void;
}

const GRAIN_MODE_LABELS: Record<GrainMode, string> = {
  none: "None (free)",
  single: "Single direction",
  bi: "Bi-directional",
};

export function GrainPanel({
  grainMode,
  fastMode,
  onGrainModeChange,
  onFastModeChange,
}: GrainPanelProps) {
  return (
    <div>
      <div>
        <div style={styles.label}>Grain Mode</div>
        <div style={styles.hint}>Fabric grain runs top → bottom</div>
        {(["none", "single", "bi"] as const).map((mode) => (
          <label key={mode} style={styles.radioRow}>
            <input
              type="radio"
              name="grain-mode"
              checked={grainMode === mode}
              onChange={() => onGrainModeChange(mode)}
            />
            <span style={{ fontSize: 12 }}>{GRAIN_MODE_LABELS[mode]}</span>
          </label>
        ))}
      </div>

      <div style={{ marginTop: 10 }}>
        <label style={styles.checkRow}>
          <input
            type="checkbox"
            checked={fastMode}
            onChange={(e) => onFastModeChange(e.target.checked)}
          />
          <span style={{ fontSize: 12 }}>Fast mode (bbox)</span>
        </label>
      </div>
    </div>
  );
}

const styles = {
  label: {
    fontSize: 11,
    fontWeight: 600 as const,
    textTransform: "uppercase" as const,
    letterSpacing: "0.05em",
    color: "var(--color-text-muted)",
    marginBottom: 4,
  },
  hint: {
    fontSize: 11,
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
