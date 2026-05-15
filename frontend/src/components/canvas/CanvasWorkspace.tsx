// Main Konva canvas component for the visual workspace.
// Handles zoom/pan, R-key rotation, and per-piece rotation handle.

import { useRef, useState, useEffect, useCallback } from "react";
import { Stage, Layer, Rect, Line, Circle } from "react-konva";
import type Konva from "konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { useCollisions } from "../../hooks/useCollisions";
import { computePlacements } from "../../utils/placement";
import { PieceShape } from "./PieceShape";
import { ViewportControls } from "./ViewportControls";

const FABRIC_HEIGHT_MM = 99_000;
const HANDLE_MARGIN_MM = 20;

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

  const collidingIds = useCollisions(placements, pieces, fabricWidthMm);

  // Ref to Layer 2 (pieces + handles) for direct Konva node manipulation during
  // rotation drag, avoiding React re-renders and the collision-detection overhead
  // they carry on every mousemove.
  const layer2Ref = useRef<Konva.Layer | null>(null);

  // Auto-fit when a new set of pieces is imported.
  // Use computePlacements(pieces) directly to avoid a stale-closure on `placements`
  // (usePlacements resets placement state asynchronously, so the prop may still
  // hold the previous import's values when this effect fires).
  useEffect(() => {
    if (pieces.length === 0) return;
    const id = setTimeout(() => {
      fitToContent(computePlacements(pieces), pieces, stageSize.w, stageSize.h);
    }, 0);
    return () => clearTimeout(id);
  // eslint-disable-next-line react-hooks/exhaustive-deps -- fire only on new import
  }, [pieces]);

  // R key: rotate selected piece by 90° CW
  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.key === "r" || e.key === "R") && selectedPieceId !== null) {
        const current = placements.find((p) => p.pieceId === selectedPieceId);
        if (!current) return;
        const rotationDeg = (current.rotationDeg + 90) % 360;
        updatePlacement(selectedPieceId, { rotationDeg });
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [selectedPieceId, placements, updatePlacement]);

  // Manual panning: track mousedown on empty Stage area, update transform on mousemove.
  // Using refs avoids stale closures and prevents re-renders during pan.
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
    fitToContent(placements, pieces, stageSize.w, stageSize.h);
  };

  // Compute rotation handle position for selected piece.
  // Handle distance scales with the piece so it always lands outside the bbox.
  const rotationHandle = (() => {
    if (!selectedPieceId) return null;
    const pl = placements.find((p) => p.pieceId === selectedPieceId);
    const piece = pieces.find((p) => p.id === selectedPieceId);
    if (!pl || !piece) return null;

    const cx = pl.x + piece.bbox.width / 2;
    const cy = pl.y + piece.bbox.height / 2;
    const handleDist = Math.max(piece.bbox.width, piece.bbox.height) / 2 + HANDLE_MARGIN_MM;
    const rad = ((pl.rotationDeg - 90) * Math.PI) / 180;
    const hx = cx + handleDist * Math.cos(rad);
    const hy = cy + handleDist * Math.sin(rad);
    return { cx, cy, hx, hy, handleDist };
  })();

  // Pin rotationHandle in a ref so drag handlers don't close over a stale value
  const rotationHandleRef = useRef(rotationHandle);
  rotationHandleRef.current = rotationHandle;

  const handleRotateDragMove = useCallback((e: KonvaEventObject<DragEvent>) => {
    const rh = rotationHandleRef.current;
    if (!selectedPieceId || !rh) return;
    const { cx, cy } = rh;
    const angle = Math.atan2(e.target.y() - cy, e.target.x() - cx) * (180 / Math.PI);
    // atan2 = 0 means "right"; rotate +90 so that "up" = 0° Konva rotation
    const rotationDeg = (angle + 90 + 360) % 360;

    // Directly mutate Konva nodes instead of going through React state.
    // This avoids re-renders (and the collision detection they trigger) on every
    // mousemove, and prevents react-konva from resetting the Circle's x/y props
    // mid-drag, which would cause the handle to snap back to the arc each frame.
    const layer = layer2Ref.current;
    if (layer) {
      layer.findOne<Konva.Group>(`#piece-${selectedPieceId}`)?.rotation(rotationDeg);
      layer.findOne<Konva.Line>('#rotation-line')?.points([cx, cy, e.target.x(), e.target.y()]);
      layer.batchDraw();
    }
  }, [selectedPieceId]);

  const handleRotateDragEnd = useCallback((e: KonvaEventObject<DragEvent>) => {
    const rh = rotationHandleRef.current;
    if (!selectedPieceId || !rh) return;
    const { cx, cy, handleDist } = rh;
    const angle = Math.atan2(e.target.y() - cy, e.target.x() - cx) * (180 / Math.PI);
    const raw = (angle + 90 + 360) % 360;
    // Snap to 1° on release — fine enough for manual work, exact float stored in state.
    const snapped = Math.round(raw) % 360;
    updatePlacement(selectedPieceId, { rotationDeg: snapped });
    // Reposition handle to match snapped rotation so it doesn't jump on next render
    const snapRad = ((snapped - 90) * Math.PI) / 180;
    e.target.x(cx + handleDist * Math.cos(snapRad));
    e.target.y(cy + handleDist * Math.sin(snapRad));
  }, [selectedPieceId, updatePlacement]);

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
          <Line
            points={[fabricWidthMm, 0, fabricWidthMm, FABRIC_HEIGHT_MM]}
            stroke="#555"
            strokeWidth={1}
          />
        </Layer>

        {/* Layer 2: piece outlines + rotation handle */}
        <Layer ref={layer2Ref}>
          {placements.map((pl) => {
            const piece = pieces.find((p) => p.id === pl.pieceId);
            if (!piece) return null;
            return (
              <PieceShape
                key={piece.id}
                piece={piece}
                placement={pl}
                isSelected={piece.id === selectedPieceId}
                isColliding={collidingIds.has(piece.id)}
                onSelect={() => onSelectPiece(piece.id)}
                onDragEnd={(id, pos) => updatePlacement(id, pos)}
              />
            );
          })}

          {/* Rotation handle — only when a piece is selected */}
          {rotationHandle && (
            <>
              <Line
                id="rotation-line"
                points={[rotationHandle.cx, rotationHandle.cy, rotationHandle.hx, rotationHandle.hy]}
                stroke="#ff9800"
                strokeWidth={1}
                strokeScaleEnabled={false}
                dash={[4, 3]}
                listening={false}
              />
              <Circle
                x={rotationHandle.hx}
                y={rotationHandle.hy}
                radius={Math.max(4, 8 / transform.scale)}
                fill="#ff9800"
                stroke="white"
                strokeWidth={1.5}
                strokeScaleEnabled={false}
                draggable
                onMouseDown={(e) => { e.cancelBubble = true; }}
                onDragMove={handleRotateDragMove}
                onDragEnd={handleRotateDragEnd}
                onMouseEnter={(e) => {
                  const container = e.target.getStage()?.container();
                  if (container) container.style.cursor = "crosshair";
                }}
                onMouseLeave={(e) => {
                  const container = e.target.getStage()?.container();
                  if (container) container.style.cursor = "default";
                }}
              />
            </>
          )}
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
