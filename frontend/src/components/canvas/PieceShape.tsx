// Renders a single placed piece as a Konva Group with the piece polygon,
// optional set color, and optional grain arrow.
//
// No drag, no rotate, no collision highlight — manual editing and frontend
// collision detection were removed in the optimization round (the engine is
// authoritative for placement validity).
// Click selects (toggles) the piece — that's the only interaction here.

import { Group, Line, Arrow } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece, GrainMode } from "../../types/engine";
import type { Placement } from "../../types/canvas";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  onSelect: () => void;
  grainMode: GrainMode;
  scale: number;
  baseStroke: string;
  baseFill: string;
}

export function PieceShape({
  piece,
  placement,
  isSelected,
  onSelect,
  grainMode,
  scale,
  baseStroke,
  baseFill,
}: Props) {
  const stroke = isSelected ? "#ff9800" : baseStroke;
  const fill = isSelected ? "rgba(255, 152, 0, 0.12)" : baseFill;

  const flatPoints = piece.polygon.flatMap(([x, y]) => [x, y]);

  // Group is placed at the bbox center with offsetX/offsetY so rotation
  // is around the centre. placement.x/y is the top-left of the unrotated bbox.
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
      {grainMode !== "none" && piece.grainline_direction_deg !== null && (() => {
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
