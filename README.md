# OpenMarker

OpenMarker is an offline-first desktop tool for garment pattern layout and basic fabric nesting.

It is designed for Windows factory users who need a simple local workflow: import DXF pattern pieces, view them on a fabric workspace, run a local auto-layout pass, and prepare results for export without sending production files to a cloud service.

<p align="center">
  <a href="README_zh.md">中文</a>
</p>

## Project Status

OpenMarker is under active development and is not yet production-ready.

Current development builds include:

- local FastAPI engine running on `127.0.0.1`
- DXF import for ET CAD-style INSERT files, plus a flat modelspace fallback
- polygon normalization, CJK name handling, quantity expansion, and grainline parsing
- React + Konva workspace for previewing imported pieces and layout results
- local NFP/BLF auto layout with grain constraints, copies, cancellation, cached layout tabs, and basic metrics

Still planned:

- export flow for saved layout results
- bundled Python engine sidecar
- one-click Windows installer
- clean-machine usability and packaging validation

## Goals

- Windows-first desktop experience
- offline-first operation
- local processing for privacy and reliability
- no Docker, command line, or manual dependency setup for end users
- maintainable code with clear frontend, desktop, and engine boundaries
- practical MVP quality before advanced industrial nesting features

## Non-Goals

OpenMarker is not trying to provide cloud collaboration, account management, ERP/PLM integration, or feature parity with commercial industrial nesting suites in the first version.

## Tech Stack

| Area | Technology |
| --- | --- |
| Desktop shell | Tauri 2 |
| Frontend | React, TypeScript, Konva, Vite |
| Local engine | Python, FastAPI |
| DXF parsing | ezdxf |
| Geometry and nesting | Shapely, Pyclipper |
| Testing | Pytest, Vitest |

## Repository Layout

```text
desktop/     Tauri desktop shell and Windows packaging work
frontend/    React UI, Konva canvas, controls, and frontend tests
engine/      Python DXF parsing, geometry, layout, cache, and API code
docs/        Planning notes, implementation plans, and developer documentation
examples/    Sample input and output files for development and QA
scripts/     Local setup and helper scripts
```

## Local Development

OpenMarker is Windows-first. Use Windows PowerShell for the Tauri desktop workflow.

### Prerequisites

- Python 3.11+
- Node.js LTS
- Rust stable
- Tauri CLI v2

Install the Tauri CLI if needed:

```powershell
cargo install tauri-cli --version "^2"
```

### Start the Engine

From the repository root:

```powershell
scripts\setup-engine.bat
scripts\dev-engine.bat
```

The engine listens on `http://127.0.0.1:8765`.

### Start the Desktop App

In a second PowerShell window:

```powershell
cd frontend
npm install
cd ..
cd desktop\src-tauri
cargo tauri dev
```

Tauri starts the Vite frontend and opens the desktop window.

## Testing

Run engine tests from the repository root:

```powershell
engine\.venv\Scripts\python -m pytest engine\tests -v
```

Run frontend tests:

```powershell
cd frontend
npm test
```

Build the frontend:

```powershell
cd frontend
npm run build
```

## Roadmap

1. Harden DXF parsing and geometry normalization with real factory files.
2. Improve layout quality, runtime, cancellation, and repeatability.
3. Add local export for cached layout results.
4. Bundle the Python engine as a Tauri sidecar.
5. Ship and test a one-click Windows installer.

See [ROADMAP.md](ROADMAP.md) and [docs/dev-setup.md](docs/dev-setup.md) for more detail.

## Contributing

Contributions should preserve the project's core constraints: offline-first behavior, Windows usability, simple installation, and clear separation between UI, desktop shell, and engine logic.

Before opening a pull request, run the relevant engine and frontend tests and include the commands you used.

See [CONTRIBUTING.md](CONTRIBUTING.md), [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md), and [SECURITY.md](SECURITY.md).

## License

OpenMarker is licensed under the [Apache License 2.0](LICENSE).
