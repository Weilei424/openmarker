// Main Konva canvas component for the visual workspace.
// Renders fabric bounds, placed piece outlines, and handles zoom/pan.

import { useRef, useState, useEffect, useMemo } from "react";
import { Stage, Layer, Rect, Line } from "react-konva";
import type { Piece } from "../../types/engine";
import { computePlacements } from "../../utils/placement";
import { useViewport } from "../../hooks/useViewport";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

// Fabric extends "infinitely" downward; this is an arbitrarily large value.
const FABRIC_HEIGHT_MM = 99_000;

interface Props {
  pieces: Piece[];
  selectedPieceId: string | null;
  onSelectPiece: (id: string | null) => void;
  fabricWidthMm: number;
}

export function CanvasWorkspace({
  pieces,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [stageSize, setStageSize] = useState({ w: 800, h: 600 });

  // Measure container on mount and on resize.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;

    const measure = () => {
      setStageSize({ w: el.clientWidth, h: el.clientHeight });
    };
    measure();

    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const placements = useMemo(() => computePlacements(pieces), [pieces]);
  const { transform, setTransform, handleWheel, fitToContent, zoomIn, zoomOut } =
    useViewport();

  // Fit to content whenever the set of pieces changes (new import).
  useEffect(() => {
    if (pieces.length === 0) return;
    // Defer one tick so Stage has rendered at its final size first.
    const id = setTimeout(() => {
      fitToContent(placements, pieces, stageSize.w, stageSize.h);
    }, 0);
    return () => clearTimeout(id);
  }, [pieces]); // eslint-disable-line react-hooks/exhaustive-deps

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
          // Deselect when clicking the stage background.
          if (e.target === e.target.getStage()) onSelectPiece(null);
        }}
      >
        {/* Layer 1: fabric background bounds */}
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
          {/* Right-edge guide line */}
          <Line
            points={[fabricWidthMm, 0, fabricWidthMm, FABRIC_HEIGHT_MM]}
            stroke="#555"
            strokeWidth={1}
          />
        </Layer>

        {/* Layer 2: piece outlines */}
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
                onSelect={() => onSelectPiece(piece.id)}
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
