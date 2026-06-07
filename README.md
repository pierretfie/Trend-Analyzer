# Trend Analyzer

An AI-powered business intelligence tool that discovers market trends, generates practical advice, and records predictions for your business.

It combines:
- Business profile context (company, sector, region, products, notes)
- Custom user instructions
- Web research tools (Google/SerpAPI, DuckDuckGo, Firecrawl)
- AI models (OpenAI, Gemini, or local GGUF models)
- Scheduled research runs with persistent SQLite storage

The goal is to help a business detect meaningful external signals early, then turn those signals into action-oriented recommendations.

---

## Core Capabilities

### 1. Trend Discovery by Business Context
The analyzer uses your saved company profile and instructions to decide what matters, searches external sources for relevant trend signals, and stores discovered trends and source references in SQLite.

### 2. Advice and Recommendations
Each trend cycle generates a structured report with:
- Summary
- Trend signals
- Recommended actions
- Severity level (`low` / `medium` / `high` / `critical`)
- Source URLs

### 3. Predictions and Forecasting
AI output includes predictions with:
- Horizon (days/weeks/months/years)
- Target date
- Confidence level
- Rationale
- Linked sources

Predictions are saved to a dedicated table for follow-up tracking.

### 4. Local + API Model Support
- OpenAI API models
- Google Gemini API models
- Local GGUF models via `llama-cpp-python`

### 5. Scheduling and Automation
- Run one-off analysis immediately
- Configure recurring daily/weekly schedules
- Run a background scheduler daemon
- Web server mode starts API + scheduler together

### 6. Web Dashboard + API
- FastAPI backend
- React/Vite frontend
- Panels for model setup, business info, schedules, reports, trends, and history

---

## Architecture

### Backend (Python)
- FastAPI API server
- Typer CLI
- APScheduler-based scheduling daemon
- SQLite database (WAL mode)
- AI orchestration and tool-calling logic

### Frontend (React + TypeScript)
- Business profile and instructions setup
- Model/provider configuration UI
- Report/history and schedule controls
- Charts and visual trend summaries

### Storage
- Default data directory: `~/.Trend_analyzer/`
- Default database: `~/.Trend_analyzer/trend_analyzer.db`
- Override via environment variables:
  - `TREND_ANALYZER_DATA_DIR`
  - `TA_DATA_DIR`

---

## Quick Start

**Prerequisites:** Python 3.10+, Node.js + npm

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Install app package (CLI command)
pip install -e .

# 3. Install frontend/dev dependencies
npm run install-all

# 4. Initialize database
trend-analyzer init

# 5. Start full web app (API + scheduler)
npm run start
```

Then open [http://127.0.0.1:8765/](http://127.0.0.1:8765/) in your browser.

---

## Model Setup

Configure a provider in the **Model Setup** panel:

| Provider | Requirements |
|----------|-------------|
| **OpenAI** | API key, select `openai` as provider |
| **Gemini** | API key, select supported Gemini model, select `gemini` as provider |
| **Local** | Path to GGUF file, configure `n_ctx` and `n_gpu_layers`, select `local` as provider — requires `llama-cpp-python` |

> If no provider is configured, analysis and chat cannot run.

---

## Running Research

```bash
# Run immediately
trend-analyzer run-once

# Add a daily schedule
trend-analyzer schedule add daily --times 07:00,19:30 --label "Daily trend scan"

# Add a weekly schedule
trend-analyzer schedule add weekly --times 08:00 --weekdays mon,thu --label "Weekly strategic scan"

# List schedules
trend-analyzer schedule list

# Enable / disable / remove a schedule
trend-analyzer schedule enable <id>
trend-analyzer schedule disable <id>
trend-analyzer schedule remove <id>

# Run scheduler only (no UI)
trend-analyzer serve

# Run web app from CLI
trend-analyzer web --host 127.0.0.1 --port 8765
```

---

## How Trends, Advice, and Predictions Are Produced

Each research pass:
1. Loads business profile, user instructions, and model/search settings
2. Collects external signals from enabled search/research sources
3. Prompts the chosen AI model to analyze relevance for the business
4. Builds a structured trend report (summary / signals / actions / severity / sources)
5. Stores report and prediction records in SQLite
6. Exposes results through the API and frontend

---

## Linux Packaging

**Additional prerequisites:** `pyinstaller`, `dpkg-deb` (for `.deb`), `appimagetool` (for AppImage)

```bash
pip install -r requirements.txt
pip install -e .
npm run install-all
npm run build

# Debian package
npm run package:linux:deb

# AppImage
npm run package:linux:appimage
```

**Output files:**
- `dist/linux/trend-analyzer_0.1.0_amd64.deb`
- `dist/linux/trend-analyzer-0.1.0-x86_64.AppImage`

**Install the Debian package:**
```bash
sudo apt install ./dist/linux/trend-analyzer_0.1.0_amd64.deb
```

The package includes the bundled frontend and Python backend — no need to run from the source tree.

---

## Tech Stack

| Layer | Technologies |
|-------|-------------|
| **Backend** | Python, FastAPI, Typer, APScheduler, SQLite |
| **Frontend** | React, TypeScript, Vite, Tailwind CSS, Recharts, Mermaid |

---

## Notes

- Data is stored locally by default
- API keys are stored in the app settings table
- The scheduler runs inside the FastAPI server process in web mode
- Local model performance depends on hardware and GGUF model size
