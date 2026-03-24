# SignalForge Documentation

> **Version:** 0.1.0
> **Last Updated:** March 24, 2026

Welcome to the SignalForge documentation. This is the central index for all
project documentation, organized by area.

---

## Quick Links

| Document | Description |
|----------|-------------|
| [Product Requirements](PRD.md) | What SignalForge is and why it exists |
| [Architecture Overview](ARCHITECTURE.md) | System-level architecture and diagrams |
| [Deployment Guide](DEPLOY.md) | Railway + Vercel + Supabase deployment |

---

## Backend Documentation

The Python/FastAPI backend contains all business logic, the LLM pipeline,
database access, and API endpoints.

| Document | Description |
|----------|-------------|
| [Backend Overview](backend/README.md) | Architecture, project structure, startup flow |
| [API Reference](backend/api-reference.md) | All REST endpoints with request/response schemas |
| [Pipeline Deep Dive](backend/pipeline.md) | The 4-stage LLM pipeline from strategies to recommendations |
| [Services Layer](backend/services.md) | Strategy CRUD, chart images, API keys, reflections |
| [Database Schema](backend/database.md) | Tables, migrations, RLS, and multi-tenancy |

---

## Frontend Documentation

The React/TypeScript frontend is a dark-themed SPA that displays pipeline
results and manages strategies.

| Document | Description |
|----------|-------------|
| [Frontend Overview](frontend/README.md) | Architecture, routing, data flow |
| [Components](frontend/components.md) | Component hierarchy and patterns |

---

## Guides

Step-by-step instructions for common development tasks.

| Document | Description |
|----------|-------------|
| [Common Tasks](guides/README.md) | Adding indicators, strategies, prompts, stages |

---

## Research

Background research that informed design decisions.

| Document | Description |
|----------|-------------|
| [Sonar Pro Optimization](research/sonar-pro-optimization.md) | How to optimize prompts for Perplexity's Sonar Pro API |

---

## Project Structure

```
signalForge/
├── docs/                    ← you are here
│   ├── README.md            (this file)
│   ├── ARCHITECTURE.md      (system architecture)
│   ├── PRD.md               (product requirements)
│   ├── DEPLOY.md            (deployment guide)
│   ├── backend/             (backend documentation)
│   ├── frontend/            (frontend documentation)
│   ├── guides/              (how-to guides)
│   └── research/            (background research)
├── src/
│   ├── backend/             (Python FastAPI)
│   └── frontend/            (React TypeScript)
├── templates/               (strategy templates JSON)
└── CLAUDE.md                (AI assistant context)
```

---

## Contributing to Docs

- All docs use Markdown with relative links between files.
- Backend docs reference source files with relative paths (e.g.,
  `[orchestrator.py](../../src/backend/pipeline/orchestrator.py)`).
- Keep docs in sync with code — when you change a feature, update its doc.
- Use tables for structured data (endpoints, fields, config).
- Use code blocks for schemas, examples, and commands.
- Use Mermaid diagrams (` ```mermaid `) for flow charts when ASCII art gets
  unwieldy.
