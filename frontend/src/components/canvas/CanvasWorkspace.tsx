// Main Konva canvas component for the visual workspace.
// Handles zoom/pan, R-key rotation, and per-piece rotation handle.

import { useRef, useState, useEffect, useCallback } from "react";
import { Stage, Layer, Rect, Line, Circle, Group } from "react-konva";
import type Konva from "konva";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece, GrainMode } from "../../types/engine";
import type { Placement } from "../../types/canvas";
import { useViewport } from "../../hooks/useViewport";
import { useCollisions } from "../../hooks/useCollisions";
import { computeFitViewportFromWorldBbox } from "../../utils/placement";
import { colorForSet, fillForSet } from "../../utils/setColors";
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
  grainMode: GrainMode;
  markerLengthMm: number;
  manualEditEnabled: boolean;
}

export function CanvasWorkspace({
  pieces,
  placements,
  updatePlacement,
  selectedPieceId,
  onSelectPiece,
  fabricWidthMm,
  grainMode,
  markerLengthMm,
  manualEditEnabled,
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

  const { transform, setTransform, handleWheel, zoomIn, zoomOut } =
    useViewport();

  // World bbox after the canvas's 90° CCW rotation. Engine bbox
  // (ex_min, ey_min)→(ex_max, ey_max) maps to world
  // (ey_min, fabricWidthMm - ex_max)→(ey_max, fabricWidthMm - ex_min).
  const computeWorldBbox = useCallback((): {
    minX: number; minY: number; maxX: number; maxY: number;
  } => {
    const pieceMap = new Map(pieces.map((p) => [p.id, p]));
    let exMin = Infinity, eyMin = Infinity, exMax = -Infinity, eyMax = -Infinity;

    // Always include the fabric outline so the user sees the strip even with no placements.
    exMin = 0;
    eyMin = 0;
    exMax = fabricWidthMm;
    eyMax = Math.max(markerLengthMm, fabricWidthMm); // show at least a square chunk

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

  const collidingIds = useCollisions(placements, pieces, fabricWidthMm);

  // Ref to Layer 2 (pieces + handles) for direct Konva node manipulation during
  // rotation drag, avoiding React re-renders and the collision-detection overhead
  // they carry on every mousemove.
  const layer2Ref = useRef<Konva.Layer | null>(null);

  // Auto-fit on import + auto-fit when an auto-layout result arrives (placements
  // becomes non-empty). Other transitions (manual drag, copies change) are NOT
  // auto-fit — they'd be disruptive while the user works.
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

  // R key: rotate selected piece by 90° CW (only while manual edit is enabled).
  useEffect(() => {
    if (!manualEditEnabled) return;
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
  }, [selectedPieceId, placements, updatePlacement, manualEditEnabled]);

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
    const bb = computeWorldBbox();
    setTransform(computeFitViewportFromWorldBbox(
      bb.minX, bb.minY, bb.maxX, bb.maxY, stageSize.w, stageSize.h,
    ));
  };

  // Compute rotation handle position for selected piece.
  // Handle distance scales with the piece so it always lands outside the bbox.
  // Only shown when manual edit is enabled.
  const rotationHandle = (() => {
    if (!manualEditEnabled) return null;
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
        {/* Layer 1: fabric background bounds + marker length indicator.
            Both layers wrap content in a Group rotated 90° CCW so the fabric
            visually extends to the right (X = length axis, minimize) and the
            grain naturally points right. Engine math stays in engine coords;
            this is a pure visual transform. */}
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

        {/* Layer 2: piece outlines + rotation handle, inside the same rotation transform */}
        <Layer ref={layer2Ref}>
          <Group rotation={-90} y={fabricWidthMm}>
          {placements.map((pl) => {
            const piece = pieces.find((p) => p.id === pl.pieceId);
            if (!piece) return null;
            const setIdx = piece.setIndex ?? 0;
            // Match selection by exact id or by base id (PieceList sends base ids
            // — they refer to all copies; canvas clicks send specific copy ids).
            const baseId = piece.id.replace(/__c\d+$/, "");
            const isSelected =
              piece.id === selectedPieceId || baseId === selectedPieceId;
            return (
              <PieceShape
                key={piece.id}
                piece={piece}
                placement={pl}
                isSelected={isSelected}
                isColliding={collidingIds.has(piece.id)}
                // Toggle: re-clicking the selected piece deselects.
                onSelect={() => onSelectPiece(isSelected ? null : piece.id)}
                onDragEnd={(id, pos) => updatePlacement(id, pos)}
                grainMode={grainMode}
                scale={transform.scale}
                baseStroke={colorForSet(setIdx)}
                baseFill={fillForSet(setIdx, 0.12)}
                editable={manualEditEnabled}
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
