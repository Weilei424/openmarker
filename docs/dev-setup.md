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

**Run from Windows PowerShell** (not WSL — Tauri opens a native Windows window).

First time only — install frontend dependencies:

```powershell
cd frontend
npm install
cd ..
```

Then, open a second terminal and start the Tauri dev shell:

```powershell
cd desktop/src-tauri
cargo tauri dev
```

This starts the Vite dev server (port 1420) and opens the Tauri window automatically.

---

## Run engine tests

```sh
cd engine
.venv/bin/pytest tests/ -v         # Linux/macOS
.venv\Scripts\pytest tests\ -v     # Windows
```

---

## Generate placeholder icons (once, before cargo tauri build)

```sh
python scripts/gen-icons.py
```

Replace `desktop/src-tauri/icons/` with real artwork before shipping.

---

## Architecture notes

- Engine and frontend communicate over `http://127.0.0.1:8765` (local loopback only).
- The Tauri window is a webview wrapper around the React app; it does **not** start or supervise the engine process in Phase 1.
- In Phase 7 (packaging), the engine will be compiled with PyInstaller and wired as a Tauri sidecar so the installer bundles everything into one executable.
