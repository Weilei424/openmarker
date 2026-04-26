// Main Konva canvas component for the visual workspace.
// Renders fabric bounds, placed piece outlines, and handles zoom/pan.

import { useRef, useState, useEffect } from "react";
import { Stage, Layer, Rect, Line } from "react-konva";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

const FABRIC_HEIGHT_MM = 99_000;

interface Props {
  pieces: Piece[];
  placements: Placement[];
  updatePlacement: (id: string, delta: Partial<Omit<Placement, "pieceId">>) => void;
  selectedPieceId: string | null;
  onSelectPiece: (id: string | null) => void;
  fabricWidthMm: number;
}

export function CanvasWorkspace({
  pieces,
  placements,
  updatePlacement,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const measure = () => setStageSize({ w: el.clientWidth, h: el.clientHeight });
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const { transform, setTransform, handleWheel, fitToContent, zoomIn, zoomOut } =
    useViewport();

  useEffect(() => {
    if (pieces.length === 0) return;
    const id = setTimeout(() => {
      fitToContent(placements, pieces, stageSize.w, stageSize.h);
    }, 0);
    return () => clearTimeout(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- fire only on new import; drag updates must not re-fit the viewport
  }, [pieces]);

  const handleFit = () => {
    fitToContent(placements, pieces, stageSize.w, stageSize.h);
  };

  return (
    <div ref={containerRef} style={styles.container}>
      <Stage
        width={stageSize.w}
        height={stageSize.h}
        draggable
        scaleX={transform.scale}
        scaleY={transform.scale}
        x={transform.x}
        y={transform.y}
        onWheel={handleWheel}
        onDragEnd={(e) => {
          setTransform((t) => ({ ...t, x: e.target.x(), y: e.target.y() }));
        }}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectPiece(null);
        }}
      >
        <Layer listening={false}>
          <Rect
            x={0}
            y={0}
            width={fabricWidthMm}
            height={FABRIC_HEIGHT_MM}
            fill="rgba(255,255,255,0.04)"
            stroke="#333"
            strokeWidth={1}
          />
          <Line
            points={[fabricWidthMm, 0, fabricWidthMm, FABRIC_HEIGHT_MM]}
            stroke="#555"
            strokeWidth={1}
          />
        </Layer>

        <Layer>
          {placements.map((pl) => {
            const piece = pieces.find((p) => p.id === pl.pieceId);
            if (!piece) return null;
            return (
              <PieceShape
                key={piece.id}
                piece={piece}
                placement={pl}
                isSelected={piece.id === selectedPieceId}
                isColliding={false}
                onSelect={() => onSelectPiece(piece.id)}
                onDragEnd={(id, pos) => updatePlacement(id, pos)}
              />
            );
          })}
        </Layer>
      </Stage>

      <ViewportControls
        scale={transform.scale}
        onFit={handleFit}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
      />
    </div>
  );
}

const styles = {
  container: {
    position: "relative" as const,
    width: "100%",
    height: "100%",
    overflow: "hidden",
    background: "#111",
  },
} as const;
