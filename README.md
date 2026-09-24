# Backend — Operational Picture (Humanitarian Needs Assessment MVP)

---

## 1. What This Service Does

The backend is responsible for:
- Ingesting field reports (text, location, optional photo/file, timestamp)
- Running the AI pipeline (extraction → classification → severity → duplicate/conflict detection → priority scoring)
- Storing structured, traceable data (source, timestamp, location, confidence, verification status, original evidence — always preserved)
- Serving the human verification/edit/approval workflow
- Exposing geocoding + map data
- Detecting and exposing information gaps (not just what's known — what's *missing*)
- Providing search/filter and audit trail endpoints to the frontend dashboard

AI outputs here are always **drafts pending human review** — the backend must never auto-publish an AI classification/priority score as final without a verification step.

---

## 2. Current Implementation Status

**Current repository:**
- The backend is currently implemented using in-memory repositories.
- PostgreSQL is NOT connected.
- The backend is currently database-independent through repository interfaces.
- Alembic migrations are NOT currently present.

**Future / Planned:**
- PostgreSQL repository implementations.
- Database schema/migrations.
- Query optimization.
- Transaction boundaries.
- Relational schema decisions.

---

## 3. Tech Stack

- **Language/Framework**: Python, FastAPI, Pydantic, Uvicorn
- **Database**: In-memory repositories (PostgreSQL planned for future)
- **Auth**: None on the API; bcrypt hashing for stored user records
- **AI Provider**: Google Gemini (via `google-genai` package)
- **Testing**: pytest

---

## 4. Architecture

The architecture currently follows a layered approach:
```
FastAPI
    ↓
API Routers
    ↓
Services
    ↓
Repository Interfaces
    ↓
In-Memory Repository Implementations
```
- **FastAPI / API Routers**: Handle HTTP requests, input validation, and routing.
- **Services**: Contain the core business logic, orchestrating AI calls and data operations.
- **Repository Interfaces**: Define the data access contracts.
- **In-Memory Repository Implementations**: Provide the current volatile data storage for development and testing.

---

## 5. Project Structure

```
app/
├── ai/
├── api/
├── audit/
├── conflicts/
├── core/
├── duplicates/
├── information_gap/
├── location/
├── map/
├── models/
├── priority/
├── repositories/
├── response_activity/
├── schemas/
├── search/
├── services/
├── utils/
└── verification/

tests/
```

---

## 6. Features

The currently implemented functionality includes:
- Report management
- AI analysis/extraction
- Locations & geocoding
- Priority scoring
- Duplicate and conflict detection
- Verification workflow
- Response activities and response coverage
- Map functionality and information gaps
- Search capabilities
- Audit logging
- User/admin management (API is unauthenticated; roles drive user-management guards only)

---

## 7. API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/reports` | Submit a new field report |
| GET | `/api/reports` | List/search/filter reports |
| GET | `/api/reports/{report_id}` | Get single report |
| PATCH | `/api/reports/{report_id}` | Update a report |
| POST | `/api/reports/{report_id}/priority` | Calculate priority for a report |
| POST | `/api/reports/{report_id}/duplicates` | Detect duplicates |
| POST | `/api/reports/{report_id}/conflicts` | Detect conflicts |
| PATCH | `/api/reports/{report_id}/verify` | Human verify/edit/approve a report |
| POST | `/api/reports/{report_id}/request-assessment` | Request assessment for a report |
| GET | `/api/verification` | List verification records |
| POST | `/api/ai/analyze` | Run AI extraction on text |
| GET | `/api/analytics/response-coverage` | Get response coverage analytics |
| GET | `/api/audit` | Audit trail query |
| POST | `/api/locations/geocode` | Geocode a location |
| GET | `/api/map/reports` | Map data for reports |
| GET | `/api/map/information-gaps` | List detected information gaps |
| GET | `/api/map/responses` | Map data for response activities |
| POST | `/api/responses` | Record response activity |
| GET | `/api/responses` | List response activities |
| GET | `/api/responses/{response_id}` | Get single response activity |
| PATCH | `/api/responses/{response_id}` | Update a response activity |
| GET | `/api/search/reports` | Search reports |
| GET | `/api/users` | List users |
| PATCH | `/api/users/{user_id}` | Update a user |

---

## 8. Authentication

The API is intentionally unauthenticated: there is no login, no bearer tokens, no JWTs, and no authorization middleware. Every endpoint serves any caller identically.

- Roles (`ADMIN`, `REVIEWER`, `ASSESSOR`, `VIEWER`) still exist as attributes of stored user records; they drive user-management guards (e.g. the final-admin lockout) but do not gate HTTP access.
- Passwords are never stored, returned or logged in plaintext — only bcrypt hashes are kept on user records, used when seeding/creating user rows rather than for any login flow.

---

## 9. AI Integration

AI output is handled through the backend workflow, relying on Google Gemini. Outputs are drafts pending human review.
Configured via:
- `GEMINI_API_KEY`: API key for Gemini.
- `GEMINI_MODEL`: Model identifier (e.g., `gemini-2.5-flash`).
- `AI_MAX_RETRIES`: Number of additional attempts for transient failures (must not be negative).
- `AI_RETRY_BACKOFF_SECONDS`: Delay between retries.

---

## 10. Geocoding

Geocoding is handled via the configured `GEOCODER_PROVIDER` (e.g., `"stub"` for local development offline mode).

---

## 11. Environment Variables

Configure the system by creating a `.env` file based on `.env.example`. Do not commit real secrets.

- `APP_NAME`: Name of the application.
- `APP_VERSION`: Current version.
- `ENVIRONMENT`: e.g., `development` or `production`.
- `CORS_ORIGINS`: Comma-separated allowed origins (Production CORS cannot use wildcard `*`).
- `GEMINI_API_KEY`: API Key for Google Gemini.
- `GEMINI_MODEL`: Target Gemini model.
- `AI_MAX_RETRIES`: Max retries for AI.
- `AI_RETRY_BACKOFF_SECONDS`: Backoff for AI retries.
- `GEOCODER_PROVIDER`: Target geocoding provider.

---

## 12. Setup

Ensure you have Python 3.10+ installed.

1. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and adjust the variables.
4. Run the application:
   ```bash
   uvicorn app.main:app --reload
   ```

---

## 13. Testing

Testing is handled via `pytest`. The test suite currently validates the in-memory backend logic.
Run the tests using:
```bash
pytest
```
Currently, the verified test suite has **562 passing tests**.

---

## 14. Priority Calculation (Phase 8)

The final priority is **computed by the backend**, never by the AI. Gemini
only extracts claims (severity, affected population, vulnerability, time
sensitivity, evidence quotes); the backend converts those claims into
0-100 factor scores, applies the fixed weights and derives the level.

**Formula** (weights total 100%):

```
final_score =
    severity_score              * 0.30
    + affected_population_score * 0.25
    + vulnerability_score       * 0.20
    + time_sensitivity_score    * 0.15
    + evidence_verification_score * 0.10
```

**Levels:** 85-100 → CRITICAL · 70-84 → HIGH · 40-69 → MEDIUM · 0-39 → LOW.
Boundaries are inclusive on the lower side (≥).

**Factor mappings (deterministic):**

| Factor | Claim → score |
|---|---|
| Severity | CRITICAL→100, HIGH→75, MEDIUM→50, LOW→25 |
| Affected population | 0→0 · 1-99→25 · 100-499→50 · 500-999→75 · ≥1000→100 |
| Vulnerability | 0 groups→50 · 1→60 · 2→80 · ≥3→100 |
| Time sensitivity | keyword bands: critical/immediate→100 · 24h/tomorrow→85 · urgent/48-72h→70 · days/week→40 · not urgent/routine→20 · unrecognized→50 |
| Evidence/verification | 0 items→10 · 1→40 · 2→50 · ≥3→60 (capped: human verification not implemented) |

**Missing/unknown handling (documented, never invented):**
- Missing severity, population, vulnerability or time sensitivity → neutral
  default 50 (absence is "unknown", not an opinion).
- Missing evidence → weak base 10 (missing evidence is not verification).
- A report carrying **no** usable claim at all → `422` business error
  instead of a fabricated score.

Endpoint: `POST /api/reports/{report_id}/priority` (see `app/services/priority_service.py`).
