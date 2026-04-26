// Renders a single pattern piece as a Konva Group (closed polygon).
// Click to select; drag to reposition; rotation handle when selected.

import { Line } from "react-konva";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  isColliding: boolean;
  onSelect: () => void;
  onDragEnd: (id: string, pos: { x: number; y: number }) => void;
}

// onDragEnd is wired to Konva drag events in Task 6 (draggable Group rewrite).
export function PieceShape({ piece, placement, isSelected, isColliding, onSelect, onDragEnd: _onDragEnd }: Props) {
  const stroke = isColliding ? "#e53935" : isSelected ? "#ff9800" : "#4a9eff";
  const fill = isColliding
    ? "rgba(229, 57, 53, 0.25)"
    : isSelected
    ? "rgba(255, 152, 0, 0.12)"
    : "rgba(74, 158, 255, 0.08)";

  const points = piece.polygon.flatMap(([x, y]) => [placement.x + x, placement.y + y]);

  return (
    <Line
      points={points}
      closed={true}
      stroke={stroke}
      fill={fill}
      strokeWidth={1}
      strokeScaleEnabled={false}
      onClick={onSelect}
      onTap={onSelect}
      onMouseEnter={(e) => {
        const container = e.target.getStage()?.container();
        if (container) container.style.cursor = "pointer";
      }}
      onMouseLeave={(e) => {
        const container = e.target.getStage()?.container();
        if (container) container.style.cursor = "default";
      }}
    />
  );
}
