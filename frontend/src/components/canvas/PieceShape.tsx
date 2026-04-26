// Renders a single pattern piece as a draggable Konva Group.
// Drag repositions the piece (snapped to 10 mm grid).
// Selected pieces show an orange outline; colliding pieces show red.

import { Group, Line } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { snapToGrid } from "../../utils/placement";

interface Props {
  piece: Piece;
  placement: Placement;
  isSelected: boolean;
  isColliding: boolean;
  onSelect: () => void;
  onDragEnd: (id: string, pos: { x: number; y: number }) => void;
}

export function PieceShape({
  piece,
  placement,
  isSelected,
  isColliding,
  onSelect,
  onDragEnd,
}: Props) {
  const stroke = isColliding ? "#e53935" : isSelected ? "#ff9800" : "#4a9eff";
  const fill = isColliding
    ? "rgba(229, 57, 53, 0.25)"
    : isSelected
    ? "rgba(255, 152, 0, 0.12)"
    : "rgba(74, 158, 255, 0.08)";

  // Polygon points in Group-local coordinates (piece is at origin)
  const flatPoints = piece.polygon.flatMap(([x, y]) => [x, y]);

  // Group is placed at the bbox center with offsetX/offsetY so rotation
  // is around the centre. placement.x/y is the top-left of the unrotated bbox.
  const cx = piece.bbox.width / 2;
  const cy = piece.bbox.height / 2;

  const handleDragEnd = (e: KonvaEventObject<DragEvent>) => {
    // Group position after drag: (placement.x + cx + drag_delta_x, placement.y + cy + drag_delta_y)
    // Recover top-left: subtract cx/cy, then snap.
    const rawX = e.target.x() - cx;
    const rawY = e.target.y() - cy;
    onDragEnd(piece.id, { x: snapToGrid(rawX), y: snapToGrid(rawY) });
  };

  const handleMouseEnter = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "grab";
  };

  const handleMouseLeave = (e: KonvaEventObject<MouseEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "default";
  };

  const handleDragStart = (e: KonvaEventObject<DragEvent>) => {
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "grabbing";
  };

  return (
    <Group
      x={placement.x + cx}
      y={placement.y + cy}
      offsetX={cx}
      offsetY={cy}
      rotation={placement.rotationDeg}
      draggable
      onClick={onSelect}
      onTap={onSelect}
      onDragStart={handleDragStart}
      onDragEnd={handleDragEnd}
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
        listening={false}
      />
    </Group>
  );
}
