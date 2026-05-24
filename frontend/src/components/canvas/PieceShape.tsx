// Renders a single placed piece as a Konva Group with the piece polygon,
// optional set color, and optional grain arrow.

import { Group, Line, Arrow } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  onSelect: () => void;
  showGrainline: boolean;
  scale: number;
  baseStroke: string;
  baseFill: string;
}

export function PieceShape({
  piece,
  placement,
  isSelected,
  onSelect,
  showGrainline,
  scale,
  baseStroke,
  baseFill,
}: Props) {
  const stroke = isSelected ? "#ff9800" : baseStroke;
  const fill = isSelected ? "rgba(255, 152, 0, 0.12)" : baseFill;

  const flatPoints = piece.polygon.flatMap(([x, y]) => [x, y]);

  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;

  const handleMouseEnter = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "pointer";
  };

  const handleMouseLeave = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "default";
  };

  return (
    <Group
      id={`piece-${piece.id}`}
      x={placement.x + cx}
      y={placement.y + cy}
      offsetX={cx}
      offsetY={cy}
      rotation={placement.rotationDeg}
      onClick={onSelect}
      onTap={onSelect}
      onMouseDown={(e) => { e.cancelBubble = true; }}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <Line
        points={flatPoints}
        closed={true}
        stroke={stroke}
        fill={fill}
        strokeWidth={1}
        strokeScaleEnabled={false}
      />
      {showGrainline && piece.grainline_direction_deg !== null && (() => {
        const arrowLen = 50 / scale;
        const rad = (piece.grainline_direction_deg * Math.PI) / 180;
        return (
          <Arrow
            points={[
              cx - (arrowLen / 2) * Math.cos(rad),
              cy - (arrowLen / 2) * Math.sin(rad),
              cx + (arrowLen / 2) * Math.cos(rad),
              cy + (arrowLen / 2) * Math.sin(rad),
            ]}
            fill="#facc15"
            stroke="#facc15"
            strokeWidth={1.5}
            strokeScaleEnabled={false}
            pointerLength={8 / scale}
            pointerWidth={6 / scale}
            listening={false}
          />
        );
      })()}
    </Group>
  );
}
