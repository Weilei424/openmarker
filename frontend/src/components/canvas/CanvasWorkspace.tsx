// Konva canvas for the visual marker workspace.
// Read-only: pieces are rendered as the engine returned them. Selection (click
// to highlight) is the only interaction here. Drag/rotate/collision-highlight
// were removed in the optimization round; the engine is authoritative.

import { useRef, useState, useEffect, useCallback } from "react";
import { Stage, Layer, Rect, Line, Group } from "react-konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { computeFitViewportFromWorldBbox } from "../../utils/placement";
import { colorForSet, fillForSet } from "../../utils/setColors";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

const FABRIC_HEIGHT_MM = 99_000;

interface Props {
  pieces: Piece[];
  placements: Placement[];
  selectedPieceId: string | null;
  onSelectPiece: (id: string | null) => void;
  fabricWidthMm: number;
  showGrainline: boolean;
  markerLengthMm: number;
}

export function CanvasWorkspace({
  pieces,
  placements,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
  showGrainline,
  markerLengthMm,
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

  const { transform, setTransform, handleWheel, zoomIn, zoomOut } = useViewport();

  // World bbox after the canvas's 90° CCW rotation. Engine bbox
  // (ex_min, ey_min)→(ex_max, ey_max) maps to world
  // (ey_min, fabricWidthMm - ex_max)→(ey_max, fabricWidthMm - ex_min).
  const computeWorldBbox = useCallback((): {
    minX: number; minY: number; maxX: number; maxY: number;
  } => {
    const pieceMap = new Map(pieces.map((p) => [p.id, p]));

    // Always include the fabric outline so the user sees the strip even with no placements.
    let exMin = 0;
    let eyMin = 0;
    let exMax = fabricWidthMm;
    let eyMax = Math.max(markerLengthMm, fabricWidthMm);

    for (const pl of placements) {
      const piece = pieceMap.get(pl.pieceId);
      if (!piece) continue;
      exMin = Math.min(exMin, pl.x);
      eyMin = Math.min(eyMin, pl.y);
      exMax = Math.max(exMax, pl.x + piece.bbox.width);
      eyMax = Math.max(eyMax, pl.y + piece.bbox.height);
    }

    return {
      minX: eyMin,
      minY: fabricWidthMm - exMax,
      maxX: eyMax,
      maxY: fabricWidthMm - exMin,
    };
  }, [pieces, placements, fabricWidthMm, markerLengthMm]);

  // Auto-fit on import + when an auto-layout result arrives (placements become non-empty).
  useEffect(() => {
    if (pieces.length === 0) return;
    const id = setTimeout(() => {
      const bb = computeWorldBbox();
      setTransform(computeFitViewportFromWorldBbox(
        bb.minX, bb.minY, bb.maxX, bb.maxY, stageSize.w, stageSize.h,
      ));
    }, 0);
    return () => clearTimeout(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally fires on import + new placements
  }, [pieces, placements.length === 0]);

  // Manual panning: track mousedown on empty Stage area, update transform on mousemove.
  const panningRef = useRef<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const onWindowMouseUp = () => { panningRef.current = null; };
    window.addEventListener("mouseup", onWindowMouseUp);
    return () => window.removeEventListener("mouseup", onWindowMouseUp);
  }, []);

  const handleStageMouseDown = useCallback((e: KonvaEventObject<MouseEvent>) => {
    if (e.target !== e.target.getStage()) return;
    panningRef.current = { x: e.evt.clientX, y: e.evt.clientY };
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "grabbing";
  }, []);

  const handleStageMouseMove = useCallback((e: KonvaEventObject<MouseEvent>) => {
    if (!panningRef.current) return;
    const dx = e.evt.clientX - panningRef.current.x;
    const dy = e.evt.clientY - panningRef.current.y;
    panningRef.current = { x: e.evt.clientX, y: e.evt.clientY };
    setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
  }, [setTransform]);

  const handleStageMouseUp = useCallback((e: KonvaEventObject<MouseEvent>) => {
    if (!panningRef.current) return;
    panningRef.current = null;
    const container = e.target.getStage()?.container();
    if (container) container.style.cursor = "default";
  }, []);

  const handleFit = () => {
    const bb = computeWorldBbox();
    setTransform(computeFitViewportFromWorldBbox(
      bb.minX, bb.minY, bb.maxX, bb.maxY, stageSize.w, stageSize.h,
    ));
  };

  return (
    <div ref={containerRef} style={styles.container}>
      <Stage
        width={stageSize.w}
        height={stageSize.h}
        scaleX={transform.scale}
        scaleY={transform.scale}
        x={transform.x}
        y={transform.y}
        onWheel={handleWheel}
        onMouseDown={handleStageMouseDown}
        onMouseMove={handleStageMouseMove}
        onMouseUp={handleStageMouseUp}
        onClick={(e) => {
          if (e.target === e.target.getStage()) onSelectPiece(null);
        }}
      >
        {/* Layer 1: fabric background + marker-length indicator.
            Both layers wrap content in a Group rotated 90° CCW so the fabric
            visually extends to the right and the grain naturally points right.
            Engine math stays in engine coords; this is a pure visual transform. */}
        <Layer listening={false}>
          <Group rotation={-90} y={fabricWidthMm}>
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
            {markerLengthMm > 0 && (
              <Line
                points={[0, markerLengthMm, fabricWidthMm, markerLengthMm]}
                stroke="#facc15"
                strokeWidth={1.5}
                strokeScaleEnabled={false}
                dash={[8, 6]}
              />
            )}
          </Group>
        </Layer>

        {/* Layer 2: piece outlines (read-only) */}
        <Layer>
          <Group rotation={-90} y={fabricWidthMm}>
            {placements.map((pl) => {
              const piece = pieces.find((p) => p.id === pl.pieceId);
              if (!piece) return null;
              const setIdx = piece.setIndex ?? 0;
              const baseId = piece.id.replace(/__c\d+$/, "");
              const isSelected =
                piece.id === selectedPieceId || baseId === selectedPieceId;
              return (
                <PieceShape
                  key={piece.id}
                  piece={piece}
                  placement={pl}
                  isSelected={isSelected}
                  onSelect={() => onSelectPiece(isSelected ? null : piece.id)}
                  showGrainline={showGrainline}
                  scale={transform.scale}
                  baseStroke={colorForSet(setIdx)}
                  baseFill={fillForSet(setIdx, 0.12)}
                />
              );
            })}
          </Group>
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
