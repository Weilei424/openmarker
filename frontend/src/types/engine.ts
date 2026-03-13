// Types for responses from the local Python engine API (http://127.0.0.1:8765)

export interface PingResponse {
  status: "ok" | "error";
  message: string;
  version: string;
}

export type EngineStatus = "unknown" | "connecting" | "connected" | "error";

export interface BoundingBox {
  min_x: number;
  min_y: number;
  max_x: number;
  max_y: number;
  width: number;
  height: number;
}

export interface Piece {
  id: string;
  name: string;
  polygon: [number, number][];
  area: number;
  bbox: BoundingBox;
  is_valid: boolean;
  validation_notes: string[];
}

export interface ImportDxfResponse {
  pieces: Piece[];
  piece_count: number;
  skipped_count: number;
  warnings: string[];
}

export type ImportStatus = "idle" | "loading" | "success" | "error";
