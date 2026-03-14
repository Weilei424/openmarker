// Sidebar panel for setting fabric roll width.

interface Props {
  fabricWidthMm: number;
  onChange: (widthMm: number) => void;
}

export function FabricPanel({ fabricWidthMm, onChange }: Props) {
  const handleBlur = (e: React.FocusEvent<HTMLInputElement>) => {
    let v = Number(e.target.value);
    if (isNaN(v) || v < 100) v = 100;
    if (v > 5000) v = 5000;
    onChange(v);
  };

  return (
    <div style={styles.root}>
      <label style={styles.label} htmlFor="fabric-width">
        Fabric width (mm)
      </label>
      <input
        id="fabric-width"
        type="number"
        min={100}
        max={5000}
        step={10}
        value={fabricWidthMm}
        onChange={(e) => onChange(Number(e.target.value))}
        onBlur={handleBlur}
        style={styles.input}
      />
      <div style={styles.display}>{fabricWidthMm} mm wide</div>
    </div>
  );
}

const styles = {
  root: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  label: {
    fontSize: 11,
    color: "var(--color-text-muted)",
  },
  input: {
    width: "100%",
    boxSizing: "border-box" as const,
    background: "rgba(255,255,255,0.06)",
    border: "1px solid var(--color-border)",
    borderRadius: 4,
    color: "var(--color-text)",
    fontSize: 13,
    padding: "4px 8px",
  },
  display: {
    fontSize: 11,
    color: "var(--color-text-muted)",
  },
} as const;
