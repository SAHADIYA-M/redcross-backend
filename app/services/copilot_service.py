"""CopilotService for RedCross Nexus — RAG Copilot query answering over evidence field reports."""

from __future__ import annotations

import os
from typing import Any

NO_EVIDENCE_ANSWER = (
    "No evidence found. No field reports matched the query, so I cannot "
    "provide an evidence-backed answer."
)


class CopilotService:
    """Service to answer queries using RAG over stored field reports.

    Every statement in the returned answer is grounded in retrieved reports:
    - with zero citations the answer says no evidence was found and never
      invents a location, facility or need;
    - when Gemini is unavailable the fallback repeats ONLY what the citations
      actually hold;
    - a missing location name is reported as "unknown location", never as a
      fabricated place name.
    """

    def __init__(self, database_url: str, api_key: str | None = None) -> None:
        self.database_url = database_url
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def answer_query(self, query: str) -> dict[str, Any]:
        """Query top matching field reports by vector similarity and return an evidence-backed answer with citations."""
        import psycopg
        from pgvector.psycopg import register_vector
        from database.scripts.embedding_utils import embed_text

        # 1. Embed user query
        query_vector = embed_text(query)

        citations = []

        # 2. Retrieve top-matching reports from database
        with psycopg.connect(self.database_url, prepare_threshold=None) as conn:
            register_vector(conn)
            sql = """
                SELECT 
                    fr.report_id::text,
                    fr.raw_content,
                    l.name AS location_name,
                    1 - (fr.embedding <=> %s::vector) AS similarity
                FROM field_reports fr
                LEFT JOIN locations l ON fr.location_id = l.location_id
                WHERE fr.embedding IS NOT NULL
                ORDER BY fr.embedding <=> %s::vector ASC
                LIMIT 5;
            """
            with conn.cursor() as cur:
                cur.execute(sql, (query_vector, query_vector))
                for row in cur.fetchall():
                    report_id, raw_content, loc_name, sim = row
                    similarity_val = float(sim) if sim is not None else 0.0
                    citations.append({
                        "report_id": report_id,
                        "location_name": loc_name,
                        "similarity": round(similarity_val, 3),
                        "snippet": raw_content[:100] if raw_content else "",
                    })

        if not citations:
            # No retrieved evidence: never fabricate an answer or a location.
            return {"answer": NO_EVIDENCE_ANSWER, "citations": []}

        context_snippets = [
            f"Report [{citation['report_id'][:8]}] at "
            f"{citation['location_name'] or 'unknown location'}: "
            f"{citation['snippet']}"
            for citation in citations
        ]

        # 3. Generate answer via Gemini or a grounded structured fallback
        answer = None
        if self.api_key:
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)
                prompt = (
                    "You are the RedCross Nexus Disaster Response RAG Copilot.\n"
                    "Answer the user's question concisely based ONLY on the evidence field reports provided below.\n\n"
                    f"QUESTION: {query}\n\n"
                    "EVIDENCE REPORTS:\n" + "\n".join(context_snippets)
                )
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                if response and response.text:
                    answer = response.text.strip()
            except Exception:
                answer = None

        if not answer:
            # Deterministic fallback grounded in the retrieved citations: it
            # reproduces only report ids, locations and snippets actually found.
            lines = [
                f"- {citation['report_id']}: "
                f"{citation['location_name'] or 'unknown location'}: "
                f"{citation['snippet'] or 'no snippet'}"
                for citation in citations
            ]
            answer = (
                f"Based on {len(citations)} field report(s):\n"
                + "\n".join(lines)
            )

        return {
            "answer": answer,
            "citations": citations,
        }
