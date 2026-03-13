// Sidebar list of imported pattern pieces.
// Displays name, dimensions, and area for each piece.

import type { Piece } from "../../types/engine";

interface Props {
  pieces: Piece[];
}

export function PieceList({ pieces }: Props) {
  if (pieces.length === 0) return null;

  return (
    <div style={styles.list}>
      {pieces.map((piece) => (
        <div key={piece.id} style={styles.item}>
          <div style={styles.name}>{piece.name}</div>
          <div style={styles.meta}>
            {piece.bbox.width.toFixed(1)} × {piece.bbox.height.toFixed(1)} mm
            &nbsp;·&nbsp;
            {(piece.area / 100).toFixed(1)} cm²
          </div>
          {piece.validation_notes.length > 0 && (
            <div style={styles.warning}>geometry repaired</div>
          )}
        </div>
      ))}
    </div>
  );
}

const styles = {
  list: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 4,
  },
  item: {
    padding: "6px 8px",
    background: "rgba(255,255,255,0.04)",
    borderRadius: 4,
    border: "1px solid var(--color-border)",
  },
  name: {
    fontSize: 12,
    fontWeight: 600,
    color: "var(--color-text)",
    marginBottom: 2,
  },
  meta: {
    fontSize: 11,
    color: "var(--color-text-muted)",
  },
  warning: {
    fontSize: 11,
    color: "var(--color-warning)",
    marginTop: 2,
  },
} as const;
