// Canvas/viewport types for the visual workspace (Phase 3+).

export interface Placement {
  pieceId: string;
  x: number;           // mm — top-left of unrotated bbox from workspace origin
  y: number;           // mm — top-left of unrotated bbox from workspace origin
  rotationDeg: number; // degrees clockwise, normalised to [0, 360)
}

export interface ViewportTransform {
  scale: number; // pixels per mm
  x: number;     // Stage pixel offset X
  y: number;     // Stage pixel offset Y
}
