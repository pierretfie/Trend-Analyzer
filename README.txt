Trend Analyzer
==============

Trend Analyzer is an AI-powered business intelligence project that discovers market trends, generates practical advice, and records predictions for your business.

It combines:
- Business profile context (company, sector, region, products, notes)
- Custom user instructions
- Web research tools (Google/SerpAPI, DuckDuckGo, Firecrawl)
- AI models (OpenAI, Gemini, or local GGUF models)
- Scheduled research runs with persistent SQLite storage

The goal is to help a business detect meaningful external signals early, then turn those signals into action-oriented recommendations.


Core Capabilities
-----------------

1) Trend discovery by business context
- The analyzer uses your saved company profile + instructions to decide what matters.
- It searches external sources for relevant trend signals.
- It stores discovered trends and source references in SQLite.

2) Advice and recommendations
- Each trend cycle generates a structured report with:
  - Summary
  - Trend signals
  - Recommended actions
  - Severity level (low/medium/high/critical)
  - Source URLs

3) Predictions and forecasting
- The AI output includes predictions with:
  - Horizon (days/weeks/months/years)
  - Target date
  - Confidence level
  - Rationale
  - Linked sources
- Predictions are saved to a dedicated table for follow-up tracking.

4) Local + API model support
- OpenAI API models
- Google Gemini API models
- Local GGUF models through llama-cpp-python

5) Scheduling and automation
- Run one-off analysis immediately
- Configure recurring daily/weekly schedules
- Run a background scheduler daemon
- Web server mode starts API + scheduler together

6) Web dashboard + API
- FastAPI backend
- React/Vite frontend
- Panels for model setup, business info, schedules, reports, trends, and history


Architecture (High Level)
-------------------------

Backend (Python):
- FastAPI API server
- Typer CLI
- APScheduler-based scheduling daemon
- SQLite database (WAL mode)
- AI orchestration and tool-calling logic

Frontend (React + TypeScript):
- Business profile and instructions setup
- Model/provider configuration UI
- Report/history and schedule controls
- Charts and visual trend summaries

Storage:
- Default data directory: ~/.Trend_analyzer/
- Default database: ~/.Trend_analyzer/trend_analyzer.db
- Override data dir via:
  - TREND_ANALYZER_DATA_DIR
  - TA_DATA_DIR


Project Goals Supported
-----------------------

This codebase is built around these practical outcomes:
- Predict trend impact windows before they are obvious
- Advise business owners with actionable next steps
- Recognize external patterns that affect pricing, demand, supply, and risk
- Present results in readable report formats with visuals


Quick Start
-----------

Prerequisites:
- Python 3.10+
- Node.js + npm

1) Install Python dependencies

   pip install -r requirements.txt

2) Install app package (CLI command)

   pip install -e .

3) Install frontend/dev dependencies

   npm run install-all

4) Initialize database

   trend-analyzer init

5) Start full web app (API + scheduler)

   npm run start

6) Open browser

   http://127.0.0.1:8765/


Linux Packaging
---------------

You can build a Linux package from this repo after installing the frontend
dependencies and PyInstaller.

Prerequisites:
- Python 3.10+
- Node.js + npm
- `pyinstaller`
- `dpkg-deb` for `.deb` builds
- `appimagetool` for AppImage builds

Build steps:
1) Install Python dependencies

   `pip install -r requirements.txt`

2) Install the app package

   `pip install -e .`

3) Install frontend dependencies

   `npm run install-all`

4) Build the frontend

   `npm run build`

5) Build the Linux package

   Debian package:

   `npm run package:linux:deb`

   AppImage:

   `npm run package:linux:appimage`

Output:
- `dist/linux/trend-analyzer_0.1.0_amd64.deb`
- `dist/linux/trend-analyzer-0.1.0-x86_64.AppImage` if `appimagetool` is installed

Install the Debian package:

`sudo apt install ./dist/linux/trend-analyzer_0.1.0_amd64.deb`

The package includes the bundled frontend and the Python backend, so it can be
installed and run on Linux without needing to launch the repo source tree.


Model Setup
-----------

Configure one of the supported AI providers in the Model Setup panel:

- OpenAI
  - Add API key
  - Select provider as openai

- Gemini
  - Add API key
  - Choose supported Gemini model
  - Select provider as gemini

- Local model (offline/private workflows)
  - Set path to GGUF model file
  - Configure context window (n_ctx)
  - Configure GPU layers (n_gpu_layers)
  - Select provider as local
  - Requires llama-cpp-python

If no provider is configured, analysis/chat cannot run.


Running Research
----------------

Immediate run:
- trend-analyzer run-once

Add a daily schedule:
- trend-analyzer schedule add daily --times 07:00,19:30 --label "Daily trend scan"

Add a weekly schedule:
- trend-analyzer schedule add weekly --times 08:00 --weekdays mon,thu --label "Weekly strategic scan"

List schedules:
- trend-analyzer schedule list

Enable/disable/remove schedule:
- trend-analyzer schedule enable <id>
- trend-analyzer schedule disable <id>
- trend-analyzer schedule remove <id>

Run scheduler only (no UI):
- trend-analyzer serve

Run web app from CLI:
- trend-analyzer web --host 127.0.0.1 --port 8765


How Trends, Advice, and Predictions Are Produced
------------------------------------------------

Each research pass:
1. Loads business profile + user instructions + model/search settings.
2. Collects external signals from enabled search/research sources.
3. Prompts the chosen AI model to analyze relevance for the business.
4. Builds a structured trend report (summary/signals/actions/severity/sources).
5. Stores report and prediction records in SQLite.
6. Exposes results through API and frontend views.

This makes the system useful for operational monitoring and strategic planning.


Key Tech Stack
--------------

Backend:
- Python
- FastAPI
- Typer
- APScheduler
- SQLite

Frontend:
- React
- TypeScript
- Vite
- Tailwind CSS
- Recharts + Mermaid


Notes
-----

- This project stores data locally by default.
- API keys are stored in the app settings table.
- The scheduler runs inside the FastAPI server process when using web mode.
- Local model performance depends heavily on hardware and GGUF model size.
