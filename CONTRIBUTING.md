# Contributing to OpenMarker

Thank you for your interest in contributing to OpenMarker.

OpenMarker is an open-source fabric layout and marker nesting tool designed to help garment manufacturers, pattern makers, and developers access free marker technology.

We welcome contributions from developers, designers, and industry professionals.

---

# Ways to Contribute

You can help the project in several ways:

### Code Contributions

Examples include:

• Bug fixes  
• Performance improvements  
• Geometry or nesting algorithm improvements  
• UI improvements  
• DXF import/export improvements  

---

### Documentation

Examples include:

• Improving documentation  
• Adding tutorials  
• Writing developer guides  
• Improving setup instructions  

---

### Testing

Examples include:

• Testing DXF imports  
• Reporting nesting issues  
• Testing UI interactions  
• Performance testing

---

# Development Workflow

This project uses two AI agents to assist development:

Claude Code — primary implementation agent  
Codex — code review and architecture validation agent

Contributor workflow:

1. Open an Issue describing the problem or feature
2. Discuss the proposed solution
3. Implement the change
4. Submit a Pull Request
5. Code review will be performed before merging

---

# Project Architecture Principles

OpenMarker follows several important design principles:

### Offline First

The application must work fully offline.

Pattern data should never require internet access.

---

### Simple Installation

Target users are factory workers with minimal technical experience.

The application must support:

• Windows installation  
• One-click install  
• No manual dependency installation

---

### Local Processing

All geometry and nesting calculations run locally.

Benefits:

• Faster computation  
• No cloud cost  
• Protects proprietary pattern data

---

### Modular Architecture

Core components are separated:

Frontend — React UI  
Desktop Shell — Tauri  
Engine — Python nesting engine

---

# Pull Request Guidelines

When submitting a PR:

Please ensure:

• Code is readable and documented  
• No unnecessary dependencies are introduced  
• Changes follow existing architecture  
• Tests are added if applicable

---

# Coding Guidelines

### Python

• Follow PEP8  
• Use type hints when possible  
• Avoid overly complex logic  

### TypeScript / React

• Prefer functional components  
• Use clear component structure  
• Avoid unnecessary state complexity

---

# Commit Message Format

Example:
engine: improve polygon collision detection
frontend: add rotation controls
docs: update nesting algorithm explanation

Format:
area: short description

Areas:

engine  
frontend  
desktop  
docs  
tests  

---

# Good First Issues

If you're new to the project, look for issues labeled:
good first issue

These are tasks suitable for first-time contributors.

---

# Code of Conduct

All contributors must follow the project's Code of Conduct.

See:

CODE_OF_CONDUCT.md

---

# License

By contributing to OpenMarker, you agree that your contributions will be licensed under the Apache 2.0 License.
