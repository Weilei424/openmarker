import type { LayoutQuality } from "../../types/engine";

interface QualityPanelProps {
  quality: LayoutQuality;
  onChange: (q: LayoutQuality) => void;
  ultraBudgetS?: number;
  ultraSeeds?: number;
  onUltraBudgetChange?: (n: number) => void;
  onUltraSeedsChange?: (n: number) => void;
}

const OPTIONS: { value: LayoutQuality; label: string; hint: string }[] = [
  { value: "fast", label: "NFP-BLF", hint: "constructive" },
  { value: "better", label: "Genetic Algorithm — quick", hint: "180s" },
  { value: "best", label: "Genetic Algorithm — thorough", hint: "420s" },
  { value: "ultra", label: "Separation (sparrow)", hint: "best-of-N" },
];

export function QualityPanel({
  quality,
  onChange,
  ultraBudgetS = 600,
  ultraSeeds = 1,
  onUltraBudgetChange = () => {},
  onUltraSeedsChange = () => {},
}: QualityPanelProps) {
  return (
    <div>
      <p style={styles.hint}>
        Higher quality packs tighter but takes longer. Click Stop to keep the
        best result so far.
      </p>
      {OPTIONS.map((opt) => (
        <label key={opt.value} style={styles.radioRow}>
          <input
            type="radio"
            name="layout-quality"
            checked={quality === opt.value}
            onChange={() => onChange(opt.value)}
          />
          <span style={{ fontSize: 14 }}>{opt.label}</span>
          <span style={styles.optHint}>{opt.hint}</span>
        </label>
      ))}
      {quality === "ultra" && (
        <div style={styles.sepControls}>
          <label style={styles.fieldRow}>
            <span style={{ fontSize: 13 }}>Time budget (s)</span>
            <input
              type="number" min={360} max={1500} step={30}
              aria-label="time budget seconds"
              value={ultraBudgetS}
              onChange={(e) => {
                const v = Math.round(Number(e.target.value));
                if (!Number.isNaN(v)) onUltraBudgetChange(Math.min(1500, Math.max(360, v)));
              }}
              style={{ width: 70 }}
            />
          </label>
          <div style={{ fontSize: 13, marginTop: 6 }} aria-label="seeds">Seeds (best of N)</div>
          {[1, 2, 3, 4].map((n) => (
            <label key={n} style={styles.radioRow}>
              <input type="radio" name="ultra-seeds" checked={ultraSeeds === n}
                     onChange={() => onUltraSeedsChange(n)} />
              <span style={{ fontSize: 13 }}>{n}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

const styles = {
  hint: {
    fontSize: 13,
    color: "var(--color-text-muted)",
    fontStyle: "italic" as const,
    marginTop: 0,
    marginBottom: 6,
  },
  radioRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
    cursor: "pointer",
  },
  optHint: {
    fontSize: 13,
    color: "var(--color-text-muted)",
  },
  sepControls: {
    marginTop: 8,
    paddingTop: 6,
    borderTop: "1px solid var(--color-border, #ddd)",
  },
  fieldRow: {
    display: "flex",
    alignItems: "center",
    gap: 6,
    marginTop: 4,
  },
} as const;
