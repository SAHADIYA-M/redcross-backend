# Backend — Operational Picture (Humanitarian Needs Assessment MVP)

> **Status: TEMPORARY / SCAFFOLD README**
> Placeholder for the backend service/repo, written before the research document and final tech stack are confirmed. Update once those are finalized — especially Tech Stack, Environment Variables, DB Schema, and API Endpoints.

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

## 2. Tech Stack *(placeholder — pending confirmation)*

| Component | Choice (tentative) |
|---|---|
| Language/framework | TBD |
| Database | PostgreSQL (+ PostGIS for geospatial queries) |
| ORM/migrations | TBD |
| Auth | TBD |
| AI provider/SDK | TBD |
| Geocoding | OpenStreetMap/Nominatim (tentative) |
| File/photo storage | TBD |
| Testing | TBD |
| Hosting | TBD |

---

## 3. Project Structure *(placeholder — to confirm once framework is chosen)*

```
backend/
├── src/
│   ├── routes/           # REST API endpoints
│   ├── controllers/
│   ├── services/
│   │   ├── ai/           # extraction, classification, severity, duplicate/conflict, priority
│   │   ├── geocoding/
│   │   └── audit/
│   ├── models/            # DB models/schema
│   ├── middleware/         # auth, validation, error handling
│   └── config/
├── tests/
├── migrations/
├── .env.example
├── README.md              # this file
└── package.json / requirements.txt / etc.
```

---

## 4. Environment Variables *(placeholder)*

All secrets via environment variables — never hardcoded. Example `.env.example` to be created once stack is finalized:

```
DATABASE_URL=
AI_API_KEY=
GEOCODING_API_KEY=      # if needed
STORAGE_BUCKET=
JWT_SECRET=
```

---

## 5. Database Schema *(placeholder — draft after research doc review)*

Core entities expected (subject to change):

- **reports** — raw field report (text, location, media, timestamp, submitter, source)
- **extractions** — AI-extracted structured data per report (people, needs, places, facilities, time, severity), linked to source report, with confidence scores
- **needs** — classified need entries (fixed category, location, severity, status)
- **locations** — resolved/geocoded locations, with human-correction history
- **duplicates_conflicts** — links between reports flagged as duplicate or conflicting
- **priority_scores** — computed priority per need/area, with explainable rationale
- **verifications** — human review/edit/approval actions, linked to user + timestamp
- **information_gaps** — flagged areas/topics with no or stale data
- **audit_log** — who changed what, when, across all entities

Every table involving a "finding" must retain: source, timestamp, location, confidence, verification status, and a reference to original evidence.

---

## 6. API Endpoints *(placeholder — to expand into full spec)*

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/reports` | Submit a new field report |
| GET | `/api/reports` | List/search/filter reports |
| GET | `/api/reports/:id` | Get single report + linked extraction/evidence |
| POST | `/api/reports/:id/extract` | Run AI extraction on a report |
| GET | `/api/needs` | List classified needs (filterable by location, category, status, confidence) |
| PATCH | `/api/needs/:id/verify` | Human verify/edit/approve a need entry |
| GET | `/api/duplicates` | List flagged duplicate/conflicting report groups |
| GET | `/api/priority` | Get current priority rankings with rationale |
| GET | `/api/locations/:id/correct` | Human correction of ambiguous geocoding |
| GET | `/api/gaps` | List detected information gaps |
| GET | `/api/audit` | Audit trail query |

---

## 7. AI Pipeline Modules *(placeholder — prompts live in `src/services/ai/`)*

1. Information extraction
2. Need classification (fixed categories)
3. Severity assessment
4. Duplicate detection
5. Conflict detection
6. Priority recommendation (transparent rationale, not a black box)
7. Summarization / search assistance

**Hard rule:** AI must never hallucinate or invent missing information. Every module preserves uncertainty (confidence scores, explicit "unknown" fields) and returns source report references for every claim.

---

## 8. Working Rules for Implementation

For every coding change/milestone in this repo:
1. Inspect existing code first
2. Avoid rewriting working code
3. Keep dependencies minimal
4. Use environment variables for secrets
5. Test the feature
6. Fix errors
7. Explain changed files and run commands
8. Work only on the requested milestone

---

## 9. Open Items / Next Steps

- [ ] Confirm tech stack (framework, ORM, hosting)
- [ ] Finalize DB schema + write migrations
- [ ] Write full API spec
- [ ] Implement AI pipeline modules + prompts
- [ ] Set up geocoding service
- [ ] Build synthetic test dataset
- [ ] Set up basic auth
- [ ] Set up audit logging
