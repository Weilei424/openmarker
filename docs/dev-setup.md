# Local Developer Setup

## Prerequisites

| Tool | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Engine runtime |
| Node.js | LTS (20+) | Frontend build |
| Rust | stable | Tauri shell |
| Tauri CLI | v2 | Desktop build |

Install Tauri CLI: `cargo install tauri-cli --version "^2"`

---

## Engine (Python)

```sh
# First time
scripts/setup-engine.sh       # Linux/macOS
scripts\setup-engine.bat      # Windows

# Every dev session
scripts/dev-engine.sh         # Linux/macOS
scripts\dev-engine.bat        # Windows
```

Engine runs on `http://127.0.0.1:8765`. Test it:

```sh
curl http://127.0.0.1:8765/ping
# {"status":"ok","message":"OpenMarker engine running","version":"0.1.0"}
```

---

## Frontend + Tauri shell

Open a second terminal:

```sh
cd desktop/src-tauri
cargo tauri dev
```

This runs Vite dev server (port 1420) and opens the Tauri window.

---

## Run engine tests

```sh
cd engine
.venv/bin/pytest tests/ -v         # Linux/macOS
.venv\Scripts\pytest tests\ -v     # Windows
```

---

## Architecture notes

- Engine and frontend communicate over `http://127.0.0.1:8765` (local loopback only).
- The Tauri window is just a webview wrapper around the React app.
- In production (Phase 7), the engine will be bundled as a PyInstaller binary and spawned as a Tauri sidecar.
