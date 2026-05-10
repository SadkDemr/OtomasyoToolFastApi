# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A multi-user test automation platform built with FastAPI. Supports web (Selenium), mobile (Appium), and desktop (image-based) test automation. Includes AI-powered test generation via Gemini and Ollama, Git workspace management, real-time WebSocket logs, and a static HTML/JS frontend.

## Running the Project

**First-time setup (Windows):**
```bat
backend\setup.bat
```
Downloads Android SDK tools, creates a Python venv, and installs dependencies.

**Start the server:**
```bat
backend\run.bat
```
Or manually:
```bash
cd backend
python main.py
```
Server starts at `http://localhost:8000`. Web UI at `/ui`, Swagger docs at `/docs`.

**Create an admin user:**
```bash
cd backend
python make_admin.py
```

## Architecture

### Backend (`backend/`)

- **Entry point:** `main.py` — initializes SQLite DB, starts ADB device monitor loop, mounts static frontend at `/ui`, runs Uvicorn on port 8000.
- **Database:** SQLite (`test_platform.db`) via SQLAlchemy 2.x. WAL mode enabled. Schema created by `database.py::init_db()` at startup.
- **Auth:** JWT tokens (python-jose + bcrypt). Roles: `admin`, `user`. Endpoints require `Authorization: Bearer <token>`.

### Routers (`backend/routers/`)

| Router | Prefix | Purpose |
|--------|--------|---------|
| `auth_router` | `/api/auth` | Login, register, token |
| `scenarios_router` | `/api/scenarios` | Scenario & folder CRUD |
| `devices_router` | `/api/devices` | Device management (ADB sync) |
| `web_router` | `/api/web` | Selenium test execution + WebSocket logs |
| `mobile_router` | `/api/mobile` | Appium test execution + WebSocket logs |
| `emulator_router` | `/api/emulator` | Android emulator control |
| `jobs_router` | `/api/jobs` | Test job batches & execution |
| `desktop_router` | `/api/desktop` | Image-based desktop automation |
| `advanced_editor_router` | `/api/advanced-editor` | Image upload/processing |
| `admin_repositories_router` | `/admin/repositories` | Git repo admin |
| `workspace_router` | `/api/workspace` | Per-user Git workspace (branch: `user-{username}`) |
| `ai_test_generator_router` | `/api/ai-generator` | Ollama (gemma3:4b) test generation |
| `java_generator_router` | `/api/java-generator` | Java/Appium code generation |

### Services (`backend/services/`)

Business logic is isolated in services and called from routers:
- `selenium_service.py` — Selenium driver lifecycle, step execution
- `appium_service.py` — Appium client, natural language step parsing (Turkish)
- `image_service.py` — Screenshot capture and encoding for advanced editor
- `ai_service.py` — Gemini API + Ollama integration
- `device_service.py` — ADB device discovery and DB sync
- `dispatcher_service.py` — Test execution dispatch across devices
- `git_service.py` — Clone, push, pull operations on user workspaces
- `auth_service.py` — Token creation/validation

### Frontend (`backend/WebArayuz/`)

Static single-page application mounted at `/ui`. Pages communicate with the FastAPI backend via `fetch()` using Bearer token auth. WebSocket connections at `/api/web/ws/{test_id}` and `/api/mobile/ws/{test_id}` provide real-time log streaming.

Key pages: `index.html` (dashboard), `login.html`, `scenarios.html`, `jobs.html`, `mobile-test.html`, `web-test.html`, `desktop-test.html`, `admin-repos.html`, `workspace.html`, `ai-generator.html`, `java-generator.html`.

### Data Models (`backend/models/`)

- `db_models.py` — SQLAlchemy ORM: `User`, `Folder`, `Scenario`, `Job`, `JobScenario`, `JobExecution`, `TestResult`, `Device`, `JobDevice`, `DeviceSession`, `Repository`, `UserWorkspace`
- `schemas.py` — Pydantic v2 request/response schemas
- `advanced_scenario_models.py` — Models for advanced editor steps
- `models_git.py` — Git workspace Pydantic schemas

## Key Conventions

- **Language:** UI, comments, and scenario steps are primarily in Turkish.
- **Multi-user isolation:** Scenarios and folders are scoped to `user_id`. Devices have `current_user_id` for exclusive locking. Git workspaces use per-user branches (`user-{username}`).
- **AI config:** Gemini API key stored in `backend/ai_config.json` (managed via `/api/admin/ai-config`). Falls back to `GEMINI_API_KEY` env var.
- **No `.env` file:** All configuration is code-based or in `ai_config.json`.

## Dependencies

See `backend/requirements.txt`. Key versions: FastAPI 0.104.1, SQLAlchemy 2.0.23, Selenium 4.15.2, Appium-Python-Client 3.1.0, Pydantic 2.5.2.

## Desktop Automation App

A separate standalone Tkinter desktop app lives in `Desktop Otomasyon/`. It has its own `requirements.txt` and entry point (`main.py`) and is independent of the FastAPI backend.
