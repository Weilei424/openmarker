// Hook for managing Stage zoom/pan state.

import { useState, useCallback } from "react";
import type { KonvaEventObject } from "konva/lib/Node";
import type { Piece } from "../types/engine";
import type { Placement, ViewportTransform } from "../types/canvas";
import { computeFitViewport } from "../utils/placement";

const MIN_SCALE = 0.1;
const MAX_SCALE = 20;
const SCALE_STEP = 1.1;

export function useViewport() {
  const [transform, setTransform] = useState<ViewportTransform>({
    scale: 1,
    x: 0,
    y: 0,
  });

  // Zoom toward/away from the cursor position.
  const handleWheel = useCallback((e: KonvaEventObject<WheelEvent>) => {
    e.evt.preventDefault();

    const stage = e.target.getStage();
    if (!stage) return;

    const pointer = stage.getPointerPosition();
    if (!pointer) return;

    const direction = e.evt.deltaY > 0 ? -1 : 1;

    setTransform((prev) => {
      const newScale =
        direction > 0
          ? Math.min(prev.scale * SCALE_STEP, MAX_SCALE)
          : Math.max(prev.scale / SCALE_STEP, MIN_SCALE);

      // Keep the point under the cursor fixed in world-mm space.
      const mousePointMmX = (pointer.x - prev.x) / prev.scale;
      const mousePointMmY = (pointer.y - prev.y) / prev.scale;

      return {
        scale: newScale,
        x: pointer.x - mousePointMmX * newScale,
        y: pointer.y - mousePointMmY * newScale,
      };
    });
  }, []);

  const fitToContent = useCallback(
    (
      placements: Placement[],
      pieces: Piece[],
      stageW: number,
      stageH: number
    ) => {
      const vp = computeFitViewport(placements, pieces, stageW, stageH);
      setTransform(vp);
    },
    []
  );

  const zoomIn = useCallback(() => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.min(prev.scale * SCALE_STEP, MAX_SCALE),
    }));
  }, []);

  const zoomOut = useCallback(() => {
    setTransform((prev) => ({
      ...prev,
      scale: Math.max(prev.scale / SCALE_STEP, MIN_SCALE),
    }));
  }, []);

  return { transform, setTransform, handleWheel, fitToContent, zoomIn, zoomOut };
}
