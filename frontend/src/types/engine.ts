// Types for responses from the local Python engine API (http://127.0.0.1:8765)

export interface PingResponse {
  status: "ok" | "error";
  message: string;
  version: string;
}

export type EngineStatus = "unknown" | "connecting" | "connected" | "error";
