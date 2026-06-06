import type { LayoutQuality } from "../../types/engine";

interface QualityPanelProps {
  quality: LayoutQuality;
  onChange: (q: LayoutQuality) => void;
}

const OPTIONS: { value: LayoutQuality; label: string; hint: string }[] = [
  { value: "fast", label: "Fast", hint: "instant" },
  { value: "better", label: "Better", hint: "~3 min, tighter" },
  { value: "best", label: "Best", hint: "~7 min, tightest" },
];

export function QualityPanel({ quality, onChange }: QualityPanelProps) {
  return (
    <div>
      <p style={styles.hint}>
        Higher quality packs tighter but takes minutes. Click Stop to keep the
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
          <span style={{ fontSize: 12 }}>{opt.label}</span>
          <span style={styles.optHint}>{opt.hint}</span>
        </label>
      ))}
    </div>
  );
}

const styles = {
  hint: {
    fontSize: 11,
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
    fontSize: 11,
    color: "var(--color-text-muted)",
  },
} as const;
