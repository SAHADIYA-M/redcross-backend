# Rules for the AI agent (RedCross Nexus, database work)
Context: RedCross Nexus fuses fragmented flood reports into Need Clusters (duplicates and conflicts flagged, human verification required). Database: Supabase Postgres + pgvector via the Transaction pooler. Embeddings: Gemini gemini-embedding-001, 768 dimensions, one embedding per report in field_reports.embedding. Location is lat/lng + name only (no PostGIS). Backend is FastAPI (Python).
- Read DATABASE_URL and GEMINI_API_KEY from the .env file in the project root (C:\Users\sahad\red-cross\.env). Never print, log or copy them anywhere. Never hard-code them in any script.
- Use Python in a virtual environment at .venv in the project root (already git-ignored). Prefer psycopg[binary] (v3), google-genai, pgvector, python-dotenv, numpy. List packages in database/requirements.txt. If an install fails on Python 3.14, STOP and show me the error. Do not switch language or tools without asking.
- Open every database connection with prepared statements disabled (psycopg: prepare_threshold=None), because of the Transaction pooler.
- Create new files only under database/scripts, database/queries, database/tests, database/docs. Never edit schema_v2.sql or seed_synthetic_data_v2.backup.sql. Edit no other existing file unless my task says so.
- Do not run git add, git commit or git push. Ask before installing anything.
- I am a beginner. When finished, give a SHORT plain-language summary of what you did and what the results mean.
- Do only the task I gave you, then stop and wait.
