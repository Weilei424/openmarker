import type { GrainMode } from "../../types/engine";

interface GrainPanelProps {
  grainDirectionDeg: number;
  grainMode: GrainMode;
  fastMode: boolean;
  onGrainDirectionChange: (deg: number) => void;
  onGrainModeChange: (mode: GrainMode) => void;
  onFastModeChange: (enabled: boolean) => void;
}

const GRAIN_DIRECTIONS = [0, 45, 90, 135] as const;
const GRAIN_MODE_LABELS: Record<GrainMode, string> = {
  none: "None (free)",
  single: "Single direction",
  bi: "Bi-directional",
};

export function GrainPanel({
  grainDirectionDeg,
  grainMode,
  fastMode,
  onGrainDirectionChange,
  onGrainModeChange,
  onFastModeChange,
}: GrainPanelProps) {
  return (
    <div>
      <div>
        <div style={styles.label}>Grain Direction</div>
        <div style={styles.directionRow}>
          {GRAIN_DIRECTIONS.map((deg) => (
            <button
              key={deg}
              onClick={() => onGrainDirectionChange(deg)}
              style={{
                ...styles.dirBtn,
                background:
                  grainDirectionDeg === deg
                    ? "var(--color-primary, #3b82f6)"
                    : "var(--color-surface)",
                color: grainDirectionDeg === deg ? "#fff" : "var(--color-text)",
              }}
            >
              {deg}°
            </button>
          ))}
        </div>
      </div>

      <div style={{ marginTop: 10 }}>
        <div style={styles.label}>Grain Mode</div>
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
  directionRow: {
    display: "flex",
    gap: 4,
  },
  dirBtn: {
    border: "1px solid var(--color-border)",
    padding: "2px 7px",
    fontSize: 11,
    cursor: "pointer",
    borderRadius: 3,
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
