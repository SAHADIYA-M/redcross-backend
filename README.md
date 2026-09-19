# redcross-backend
# Operational Picture — Humanitarian Needs Assessment MVP

> **Status: TEMPORARY / SCAFFOLD README**
> This is a placeholder problem-statement (PS) document written before the research document has been reviewed. Once the research doc is shared, this file should be expanded/corrected section by section — especially Tech Stack, Data Sources, DB Schema, and AI Prompts, which need to be grounded in the actual findings.

---

## 1. Problem Statement

During disasters, humanitarian responders don't lack information — they lack a **usable** picture of it. Field reports, calls, messages, and photos come in fragmented, inconsistent, duplicated, and sometimes contradictory. Existing "disaster dashboards" usually just visualize whatever data is fed to them; they don't help anyone figure out **who is affected, what they need, where, and how urgent it is** — while being honest about what is uncertain or missing.

**We are explicitly not building a generic disaster-management dashboard.**

We are building a system that converts messy, fragmented humanitarian information into a **structured, location-aware, prioritized, traceable, uncertainty-aware operational picture** — where AI assists human responders, and never replaces their judgment.

Core design principle: **absence of reports ≠ absence of need.** The system must actively surface where it has no information, not just display what it has.

---

## 2. Core MVP Features

| # | Feature | Purpose |
|---|---------|---------|
| 1 | Field report submission | Text, location, optional photo/file, timestamp |
| 2 | AI extraction | Pull out people, needs, places, facilities, time, severity from raw text |
| 3 | Need classification | Map extracted needs to fixed categories |
| 4 | Geolocation + human correction | Resolve ambiguous/inconsistent location mentions, let a human fix bad matches |
| 5 | Interactive map | Visualize reports and needs geographically |
| 6 | Duplicate & conflict detection | Flag reports that likely describe the same event/need, or contradict each other |
| 7 | Transparent priority recommendation | Score/rank urgency with a visible, explainable rationale — not a black-box number |
| 8 | Human verification/edit/approval workflow | Every AI output is a draft until a human reviews it |
| 9 | Evidence/source traceability | Every claim links back to its original report(s) |
| 10 | Information-gap detection | Actively flag areas/topics with no or stale data |
| 11 | Responder dashboard | Operational view for decision-making |
| 12 | Search/filter | Find reports/needs by location, category, status, time, confidence |
| 13 | Basic audit trail | Who changed what, when |
| 14 | Continuous status updates | Needs/reports evolve over time, not one-shot snapshots |

**Non-negotiable data integrity rule:** every important finding retains — source, timestamp, location, confidence, verification status, and original evidence — at all times.

---

## 3. Research Requirements to Account For

- Fragmented / unstructured information
- Inconsistent terminology and location naming
- Duplicate and conflicting reports
- Unverified / outdated information
- Hard-to-reach and underreported communities
- Poor connectivity
- Infrastructure damage vs. actual service disruption (a damaged road ≠ the area is unreachable; a standing hospital ≠ it's functional)
- Uncertainty in early assessments (early data is sparse and shouldn't be treated as ground truth)
- Privacy / protection risks (especially for vulnerable individuals named in reports)
- Response coverage (are responders actually reaching the places with the greatest need?)

---

## 4. Data & APIs *(placeholder — to confirm against research doc)*

Preference order:
1. Field reports (our own primary data)
2. Official humanitarian APIs (e.g., ReliefWeb, HDX/Humanitarian Data Exchange, ACLED, GDACS — to verify availability/licensing)
3. Public datasets
4. OpenStreetMap / open geospatial data (Nominatim or similar for geocoding)

Avoid scraping unless genuinely necessary and permitted.

**For each external source, to be filled in once confirmed:**
- What it provides
- API availability
- Free tier / cost
- Auth/key requirements
- Licensing
- Usefulness for MVP

---

## 5. Tech Stack *(placeholder — pending confirmation)*

Single, practical, free-first stack (no unnecessary microservices):

| Layer | Choice (tentative) |
|-------|--------------------|
| Frontend | TBD |
| Backend | TBD |
| Database | PostgreSQL (+ PostGIS for geospatial queries) |
| Auth | TBD |
| AI | TBD |
| Geocoding | OpenStreetMap/Nominatim (tentative) |
| Maps | TBD (e.g., Leaflet + OSM tiles) |
| Storage | TBD |
| Hosting | TBD |
| Testing | TBD |
| Version control | GitHub |

---

## 6. AI Pipeline *(placeholder — prompts to be drafted per module)*

AI modules needed, each with structured JSON I/O:
1. Information extraction
2. Need classification
3. Severity assessment
4. Duplicate detection
5. Conflict detection
6. Priority recommendation (with visible rationale)
7. Summarization / search assistance

**Hard rule for all prompts:** AI must never hallucinate or invent missing information. Every output preserves uncertainty (confidence scores, "unknown" fields) and links to evidence (source report IDs).

---

## 7. Deliverables Checklist

- [ ] System architecture diagram
- [ ] Database schema
- [ ] REST API endpoint list
- [ ] Frontend screens/routes
- [ ] AI pipeline + prompts (per module above)
- [ ] GitHub folder structure
- [ ] Implementation phases
- [ ] Claude coding prompts per phase
- [ ] Synthetic disaster reports for testing
- [ ] MVP vs. Nice-to-have vs. Future feature split
- [ ] 2–3 minute hackathon demo script

---

## 8. Demo Flow (target)

Single disaster scenario, one continuous narrative:

**Messy field report → AI extraction → location resolution → map → priority scoring → duplicate/conflict flagging → human verification → dashboard → information-gap surfaced → evidence-backed search → final operational picture.**

---

## 9. Working Rules for Claude Coding Prompts

Every coding prompt given to Claude during implementation should instruct it to:
1. Inspect existing code first
2. Avoid rewriting working code
3. Keep dependencies minimal
4. Use environment variables for secrets
5. Test the feature
6. Fix errors
7. Explain changed files and run commands
8. Work only on the requested milestone

---

## 10. Open Items / Next Steps

- [ ] Review research document once shared — update Data & APIs, Tech Stack, DB Schema, AI Prompts sections accordingly
- [ ] Finalize tech stack
- [ ] Draft database schema
- [ ] Draft API endpoint list
- [ ] Write AI prompts for each pipeline module
- [ ] Build synthetic test dataset
- [ ] Split features into MVP / Nice-to-have / Future
- [ ] Write phase-by-phase Claude coding prompts
