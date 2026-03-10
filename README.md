# OpenMarker - Fabric Layout Tool

Offline-first Windows desktop application for garment pattern layout and basic fabric nesting.

<p align="center">
  <a href="README_zh.md">中文</a>&nbsp; • &nbsp;
</p>

## Purpose

This project is a non-profit fabric layout tool for factory users who are not technical. The product must be simple to install, simple to run, and able to work without internet access.

The app should feel like a normal Windows desktop tool:

- install with a normal `.exe` installer
- open from desktop shortcut
- import DXF exported from ET CAD
- view pattern pieces in a visual workspace
- drag, rotate, and arrange pieces manually
- run simple auto layout locally
- export layout results locally

## Product goals

### Primary goals

- Windows-first user experience
- one-click installation
- no Docker, no command line, no manual dependency setup for end users
- offline-first workflow
- local processing for privacy and performance
- architecture that is simple enough to maintain with AI-assisted development

### Non-goals for v1

- cloud deployment
- multi-user collaboration
- advanced industrial nesting parity with Gerber or Lectra
- ERP / PLM integration
- account system

## Architecture summary

The application is packaged as a Windows desktop app, but internally uses a web UI plus a local engine.

### User-facing view

1. User installs `FabricLayoutTool.exe`
2. User opens the app like a normal desktop program
3. User imports a DXF file
4. User edits or auto-generates a layout
5. User exports results to local files

### Internal architecture

- **Desktop shell:** Tauri
- **Frontend:** React + TypeScript + Konva
- **Local engine:** Python
- **Geometry libraries:** Shapely + Pyclipper
- **DXF parsing:** ezdxf

This gives a lightweight desktop app with a modern UI and a strong geometry ecosystem.

## Repository structure

```text
fabric-layout-tool/
├── README.md
├── CODEX.md
├── CLAUDE.md
├── ROADMAP.md
├── SKILLS.md
├── .github/
│   └── workflows/
├── desktop/
│   └── src-tauri/
│       ├── capabilities/
│       ├── icons/
│       └── src/
├── frontend/
│   ├── public/
│   ├── src/
│   │   ├── app/
│   │   ├── components/
│   │   │   ├── canvas/
│   │   │   ├── controls/
│   │   │   ├── layout/
│   │   │   └── pieces/
│   │   ├── hooks/
│   │   ├── lib/
│   │   ├── styles/
│   │   └── types/
│   └── tests/
├── engine/
│   ├── api/
│   ├── core/
│   │   ├── dxf/
│   │   ├── export/
│   │   ├── geometry/
│   │   ├── models/
│   │   ├── nesting/
│   │   └── utils/
│   ├── scripts/
│   └── tests/
│       ├── integration/
│       └── unit/
├── docs/
├── examples/
│   ├── input/
│   └── output/
└── scripts/
```

## Directory responsibilities

### `desktop/`
Contains the Tauri desktop shell and Windows packaging logic.

### `frontend/`
Contains the React UI. This is where canvas rendering, DXF preview, controls, and editing interactions live.

### `engine/`
Contains the Python implementation for DXF parsing, geometry normalization, layout logic, and export logic.

### `docs/`
Contains technical notes, architecture decisions, data model notes, test plans, and UI mockups.

### `examples/`
Contains sample DXF inputs and exported outputs for development and QA.

### `scripts/`
Contains developer helper scripts for local setup, linting, packaging, and release automation.

## Suggested milestones

### Milestone 1: skeleton app

- Tauri shell runs on Windows
- React UI renders a workspace
- Python engine can be invoked locally
- sample command round-trip works

### Milestone 2: DXF import and visualization

- import DXF file
- extract piece outlines
- normalize coordinates
- render pieces on canvas

### Milestone 3: manual editing

- drag pieces
- rotate pieces
- zoom and pan
- show bounds and collision warnings

### Milestone 4: simple auto layout

- define fabric width
- run basic placement algorithm
- compute layout length and utilization

### Milestone 5: export and packaging

- export layout data
- package Windows installer
- run user acceptance testing with non-technical users

## Recommended local developer setup

### Frontend

- Node.js LTS
- package manager: pnpm or npm

### Engine

- Python 3.11 (3.12+ currently unsupported because `pyclipper` fails to build)
- virtual environment

### Desktop shell

- Rust toolchain for Tauri
- Tauri prerequisites for Windows

## Development rules

- keep the app offline-first
- keep the installer simple for end users
- avoid adding server or cloud dependencies unless there is a strong reason
- prioritize correctness and usability over premature optimization
- keep the engine modular so hot paths can be rewritten later if needed

## Testing priorities

- DXF parsing correctness
- polygon normalization correctness
- layout collision correctness
- export correctness
- Windows packaging reliability
- usability testing with non-technical users

## First implementation targets

1. Create app shell and repository wiring
2. Add DXF upload flow
3. Parse simple piece outlines
4. Render pieces on canvas
5. Support manual drag and rotate
6. Show simple utilization metrics

## License

[Apache 2.0](/LICENSE)
