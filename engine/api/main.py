# OpenMarker engine API
# Local HTTP server that bridges the Tauri frontend to the Python geometry logic.
# Runs on 127.0.0.1:8765 — not exposed to the network.

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="OpenMarker Engine", version="0.1.0")

# Allow requests from the Tauri webview (file:// or localhost origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/ping")
def ping() -> dict:
    """Health check — confirms the engine process is running."""
    return {"status": "ok", "message": "OpenMarker engine running", "version": "0.1.0"}


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8765, reload=False)
