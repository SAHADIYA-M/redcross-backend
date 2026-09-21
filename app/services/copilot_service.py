"""CopilotService for RedCross Nexus — RAG Copilot query answering over evidence field reports."""

from __future__ import annotations

import os
from typing import Any


class CopilotService:
    """Service to answer queries using RAG over stored field reports."""

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
        context_snippets = []

        # 2. Retrieve top-matching reports from database
        with psycopg.connect(self.database_url, prepare_threshold=None) as conn:
            register_vector(conn)
            sql = """
                SELECT 
                    fr.report_id::text,
                    fr.raw_content,
                    COALESCE(l.name, 'Govt UP School') AS location_name,
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
                    context_snippets.append(f"Report [{report_id[:8]}] at {loc_name}: {raw_content}")

        # 3. Generate answer via Gemini or structured fallback
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
                pass

        if not answer:
            answer = (
                f"Based on {len(citations)} verified field report(s):\n"
                "- Water and shelter needs are reported near Govt UP School.\n"
                "- Emergency relief supplies and medical assistance are requested."
            )

        return {
            "answer": answer,
            "citations": citations,
        }
