// Sidebar list of imported pattern pieces.
// Displays name, dimensions, and area for each piece.
// Supports selection: clicking a piece highlights it on the canvas.

import type { Piece } from "../../types/engine";

interface Props {
  pieces: Piece[];
  selectedPieceId: string | null;
  onSelect: (id: string) => void;
}

export function PieceList({ pieces, selectedPieceId, onSelect }: Props) {
  if (pieces.length === 0) return null;

  return (
    <div style={styles.list}>
      {pieces.map((piece) => {
        const isSelected = piece.id === selectedPieceId;
        const itemStyle = {
          ...styles.item,
          ...(isSelected ? styles.itemSelected : {}),
        };
        return (
          <div key={piece.id} style={itemStyle} onClick={() => onSelect(piece.id)}>
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
        );
      })}
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
    cursor: "pointer" as const,
  },
  itemSelected: {
    background: "rgba(74, 158, 255, 0.1)",
    borderLeft: "3px solid #4a9eff",
    paddingLeft: 5, // compensate for wider border
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
