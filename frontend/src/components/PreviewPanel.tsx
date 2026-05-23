// Top-of-screen "preview panel": one thumbnail per imported piece. Independent
// of copies and canvas placements. Acts as the source-of-truth visual index.
//
// Renders only the polygon OUTLINE (no fill) so the shape is unambiguous —
// the previous semi-transparent fill produced a confusing "blue background
// with a darker shape inside" look (the fill is the polygon, the stroke is
// the same polygon — together they look like two shapes).

import type { Piece } from "../types/engine";

const THUMB_HEIGHT_PX = 56;
const THUMB_MAX_WIDTH_PX = 110;
const STRIP_HEIGHT_PX = 100;

interface Props {
  pieces: Piece[];
  selectedPieceId: string | null;
  onSelect: (id: string | null) => void;
}

export function PreviewPanel({ pieces, selectedPieceId, onSelect }: Props) {
  if (pieces.length === 0) {
    return (
      <div style={styles.strip}>
        <span style={styles.placeholder}>Import a DXF to populate the preview panel.</span>
      </div>
    );
  }

  return (
    <div style={styles.strip}>
      {pieces.map((piece) => {
        // Selected if the user clicked this thumbnail OR an expanded copy on the canvas
        // (canvas piece ids look like `${base}__c${n}` and PreviewPanel uses the base id).
        const isSelected =
          selectedPieceId === piece.id ||
          (selectedPieceId !== null &&
            selectedPieceId.replace(/__c\d+$/, "") === piece.id);

        const scale = THUMB_HEIGHT_PX / Math.max(1, piece.bbox.height);
        const thumbW = Math.min(THUMB_MAX_WIDTH_PX, Math.max(20, piece.bbox.width * scale));
        const points = piece.polygon.map(([x, y]) => `${x},${y}`).join(" ");

        return (
          <button
            key={piece.id}
            type="button"
            title={piece.name}
            onClick={() => onSelect(isSelected ? null : piece.id)}
            style={{
              ...styles.item,
              borderColor: isSelected ? "#ff9800" : "transparent",
              background: isSelected ? "rgba(255, 152, 0, 0.12)" : "transparent",
            }}
          >
            <svg
              width={thumbW}
              height={THUMB_HEIGHT_PX}
              viewBox={`0 0 ${Math.max(1, piece.bbox.width)} ${Math.max(1, piece.bbox.height)}`}
              preserveAspectRatio="xMidYMid meet"
              style={styles.svg}
            >
              <polygon
                points={points}
                fill="none"
                stroke={isSelected ? "#ff9800" : "#4a9eff"}
                strokeWidth={1.5}
                strokeLinejoin="round"
                vectorEffect="non-scaling-stroke"
              />
            </svg>
            <span style={styles.name}>{piece.name}</span>
          </button>
        );
      })}
    </div>
  );
}

const styles = {
  strip: {
    height: STRIP_HEIGHT_PX,
    background: "var(--color-surface)",
    borderBottom: "1px solid var(--color-border)",
    display: "flex",
    flexDirection: "row" as const,
    alignItems: "center",
    gap: 4,
    padding: "0 12px",
    overflowX: "auto" as const,
    overflowY: "hidden" as const,
    flexShrink: 0,
  },
  item: {
    display: "flex",
    flexDirection: "column" as const,
    alignItems: "center",
    gap: 2,
    padding: 4,
    background: "transparent",
    border: "1px solid transparent",
    borderRadius: 4,
    cursor: "pointer",
    flexShrink: 0,
  },
  svg: {
    display: "block",
  },
  name: {
    fontSize: 10,
    color: "var(--color-text-muted)",
    maxWidth: THUMB_MAX_WIDTH_PX + 8,
    overflow: "hidden" as const,
    textOverflow: "ellipsis" as const,
    whiteSpace: "nowrap" as const,
  },
  placeholder: {
    fontSize: 12,
    color: "var(--color-text-muted)",
    fontStyle: "italic" as const,
  },
} as const;
