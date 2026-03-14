// Canvas/viewport types for the visual workspace (Phase 3+).

export interface Placement {
  pieceId: string;
  x: number; // mm from workspace origin (left edge of fabric)
  y: number; // mm from workspace origin (top edge)
}

export interface ViewportTransform {
  scale: number; // pixels per mm
  x: number;     // Stage pixel offset X
  y: number;     // Stage pixel offset Y
}
