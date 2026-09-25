# RedCross CrisisSync — Backend

> Humanitarian crisis-intelligence API powering the RedCross Nexus dashboard.  
> Built with **Python · FastAPI · Google Gemini · SQLAlchemy · Supabase (PostgreSQL)**.

---

## Overview

The backend is the data and AI backbone of RedCross Nexus. It ingests raw field observations, runs a multi-stage AI pipeline (extraction → classification → duplicate/conflict detection → priority scoring), stores every artefact with a full audit trail, and serves a human verification workflow before any AI output is published.

> **AI outputs are always drafts pending human review.** The backend never auto-publishes an AI classification or priority score as final without an explicit human verification step.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| Framework | FastAPI 0.141 + Uvicorn 0.53 |
| Data validation | Pydantic (via FastAPI) |
| ORM / DB driver | SQLAlchemy 2.0 + psycopg 3 (binary) |
| Database | Supabase (PostgreSQL) — in-memory repositories used during development |
| AI Provider | Google Gemini (`google-genai` 2.24) |
| Auth | None on the API; bcrypt for stored password hashes |
| HTTP client | httpx 0.28 |
| Testing | pytest 9.1 |

---

## Architecture

```
HTTP Request
    ↓
FastAPI Routers          ← input validation, routing
    ↓
Services                 ← business logic, AI orchestration
    ↓
Repository Interfaces    ← data-access contracts (swappable)
    ↓
Implementations          ← In-Memory (dev) | PostgreSQL/Supabase (prod)
```

The repository-interface pattern means the entire service layer is database-agnostic — swapping from in-memory to PostgreSQL requires only a new repository implementation.

---

## Current Implementation Status

| Area | Status |
|------|--------|
| In-memory repositories | ✅ Fully implemented |
| PostgreSQL / Supabase repositories | 🔄 In progress |
| Alembic migrations | ❌ Not yet present |
| Query optimisation | 📋 Planned |
| Transaction boundaries | 📋 Planned |

---

## Project Structure

```
redcross-backend/
├── app/
│   ├── main.py               # FastAPI app factory, router registration, CORS
│   ├── ai/                   # Gemini integration, prompt templates
│   ├── api/                  # HTTP route handlers
│   ├── audit/                # Audit-log models and service
│   ├── conflicts/            # Conflict-detection logic
│   ├── core/                 # Settings, config, shared utilities
│   ├── duplicates/           # Duplicate-detection logic
│   ├── information_gap/      # Gap-detection models and service
│   ├── location/             # Location normalisation + geocoding
│   ├── map/                  # Map-data endpoints
│   ├── models/               # SQLAlchemy ORM models
│   ├── priority/             # Priority-scoring formula
│   ├── repositories/         # Repository interfaces + implementations
│   ├── response_activity/    # Response-activity tracking
│   ├── schemas/              # Pydantic request/response schemas
│   ├── search/               # Full-text search helpers
│   ├── services/             # Core business-logic services
│   ├── utils/                # Shared helpers
│   └── verification/         # Human verification workflow
├── database/
│   ├── schema_v2.sql         # Current PostgreSQL schema
│   ├── seed_users.sql        # Seed data for user records
│   ├── docs/                 # Database documentation
│   ├── migrations/           # SQL migration scripts
│   ├── queries/              # Named SQL queries
│   └── scripts/              # DB management scripts (RLS, etc.)
├── tests/                    # pytest test suite (562 passing tests)
├── requirements.txt
├── .env.example
└── redcross.db               # SQLite dev database (auto-created)
```

---

## Getting Started

### Prerequisites

- Python 3.10+
- A Supabase project **or** use the in-memory mode for development (no DB needed)
- A Google Gemini API key

### 1 — Clone & set up virtual environment

```bash
git clone https://github.com/SAHADIYA-M/redcross-backend.git
cd redcross-backend

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate
```

### 2 — Install dependencies

```bash
pip install -r requirements.txt
```

### 3 — Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your values (see [Environment Variables](#environment-variables) below).

### 4 — Run the server

```bash
uvicorn app.main:app --reload
```

The API is now available at [http://localhost:8000](http://localhost:8000).  
Interactive docs: [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Environment Variables

| Variable | Example | Description |
|----------|---------|-------------|
| `GEMINI_API_KEY` | `AIza...` | Google Gemini API key |
| `GEMINI_MODEL` | `gemini-2.5-flash` | Gemini model identifier |
| `DATABASE_URL` | `postgresql+psycopg://...` | Supabase / PostgreSQL connection string |
| `APP_NAME` | `RedCross Nexus` | Application name (used in responses) |
| `APP_VERSION` | `1.0.0` | Application version |
| `ENVIRONMENT` | `development` | `development` or `production` |
| `CORS_ORIGINS` | `http://localhost:5173` | Comma-separated allowed origins (no wildcard in production) |
| `AI_MAX_RETRIES` | `3` | Max retry attempts for transient Gemini failures |
| `AI_RETRY_BACKOFF_SECONDS` | `1` | Delay between retries |
| `GEOCODER_PROVIDER` | `stub` | Geocoding provider (`stub` = offline, no external calls) |

> Never commit real secrets. `.env` is git-ignored.

---

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/reports` | Submit a new field report |
| `GET` | `/api/reports` | List / search / filter reports |
| `GET` | `/api/reports/{report_id}` | Get a single report |
| `PATCH` | `/api/reports/{report_id}` | Update a report |
| `POST` | `/api/reports/{report_id}/priority` | Calculate priority score |
| `POST` | `/api/reports/{report_id}/duplicates` | Run duplicate detection |
| `POST` | `/api/reports/{report_id}/conflicts` | Run conflict detection |
| `PATCH` | `/api/reports/{report_id}/verify` | Human verify / edit / approve |
| `POST` | `/api/reports/{report_id}/request-assessment` | Request field assessment |
| `GET` | `/api/verification` | List verification records |
| `POST` | `/api/ai/analyze` | Run AI extraction on raw text |
| `GET` | `/api/analytics/response-coverage` | Response coverage analytics |
| `GET` | `/api/audit` | Audit trail query |
| `POST` | `/api/locations/geocode` | Geocode a location string |
| `GET` | `/api/map/reports` | Map data for reports |
| `GET` | `/api/map/information-gaps` | Detected information gaps |
| `GET` | `/api/map/responses` | Map data for response activities |
| `POST` | `/api/responses` | Record a response activity |
| `GET` | `/api/responses` | List response activities |
| `GET` | `/api/responses/{response_id}` | Get a single response activity |
| `PATCH` | `/api/responses/{response_id}` | Update a response activity |
| `GET` | `/api/search/reports` | Full-text report search |
| `GET` | `/api/users` | List users |
| `PATCH` | `/api/users/{user_id}` | Update a user |

Full interactive documentation is available at `/docs` (Swagger UI) and `/redoc`.

---

## Authentication

The API is **intentionally unauthenticated** — there is no login, no bearer tokens, no JWTs, and no authorization middleware. Every endpoint serves any caller identically.

- Roles (`ADMIN`, `REVIEWER`, `ASSESSOR`, `VIEWER`) exist as attributes on stored user records and drive user-management guards (e.g. the final-admin lockout), but do **not** gate HTTP access.
- Passwords are never stored, returned, or logged in plaintext — only bcrypt hashes are kept, used when seeding/creating user rows.

---

## AI Integration (Google Gemini)

The AI pipeline extracts structured claims from raw field-report text:

1. **Extraction** — needs, location, severity, affected population, vulnerability groups, time sensitivity, evidence quotes.
2. **Classification** — categorise extracted needs.
3. **Duplicate detection** — compare new reports against existing clusters.
4. **Conflict detection** — flag contradictory claims across reports.

AI output is always a **draft**; a human reviewer must verify before any score or classification is published.

---

## Priority Scoring

Priority is **computed deterministically by the backend** — Gemini only extracts raw claims; the formula converts them to scores.

```
final_score =
    severity_score               × 0.30
  + affected_population_score    × 0.25
  + vulnerability_score          × 0.20
  + time_sensitivity_score       × 0.15
  + evidence_verification_score  × 0.10
```

**Levels:** `CRITICAL` (85-100) · `HIGH` (70-84) · `MEDIUM` (40-69) · `LOW` (0-39)

| Factor | Claim → score |
|--------|--------------|
| Severity | CRITICAL→100, HIGH→75, MEDIUM→50, LOW→25 |
| Affected population | 0→0, 1-99→25, 100-499→50, 500-999→75, ≥1000→100 |
| Vulnerability groups | 0→50, 1→60, 2→80, ≥3→100 |
| Time sensitivity | immediate→100, 24h→85, 48-72h→70, days/week→40, not urgent→20 |
| Evidence | 0 items→10, 1→40, 2→50, ≥3→60 |

Missing or unknown claims default to a neutral score of 50 (absence = unknown, not an opinion). A report with **no** usable claim returns `422`.

---

## Testing

```bash
pytest
```

The test suite currently has **562 passing tests** covering all in-memory service and repository logic.

---

## Features

- Field report ingestion (text, location, optional metadata)
- AI extraction via Google Gemini
- Deterministic priority scoring
- Duplicate and conflict detection
- Human verification and approval workflow
- Geocoding and map data endpoints
- Information gap detection
- Response activity tracking and coverage analytics
- Full-text report search
- Audit logging
- User / admin management

---

## Related Repositories

- **Frontend:** [redcross-frontend](https://github.com/aishwaryanair440/redcross-frontend) — React 19 + Vite dashboard

---

## License

Internal project — RedCross Humanitarian Technology Initiative. All rights reserved.
