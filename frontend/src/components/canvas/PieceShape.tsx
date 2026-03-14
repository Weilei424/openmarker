// Renders a single pattern piece as a Konva Line (closed polygon).
// Click to select; selected pieces render in orange instead of blue.

import { Line } from "react-konva";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  onSelect: () => void;
}

export function PieceShape({ piece, placement, isSelected, onSelect }: Props) {
  const stroke = isSelected ? "#ff9800" : "#4a9eff";
  const fill = isSelected ? "rgba(255, 152, 0, 0.12)" : "rgba(74, 158, 255, 0.08)";

  // Flatten polygon vertices offset by placement position.
  const points = piece.polygon.flatMap(([x, y]) => [
    placement.x + x,
    placement.y + y,
  ]);

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
