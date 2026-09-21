"""ExtractionService for RedCross Nexus — extracts structured need codes and summaries from report text."""

from __future__ import annotations

import os
import json
from typing import Any


class ExtractionService:
    """Service to extract structured fields and needs from raw text reports."""

    def __init__(self, api_key: str | None = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    def extract_structured_report(self, text: str) -> dict[str, Any]:
        """Extract summary, needs, and location hints from raw text report."""
        # Attempt LLM extraction via Gemini if key is provided
        if self.api_key:
            try:
                from google import genai
                client = genai.Client(api_key=self.api_key)
                prompt = (
                    "Extract structured JSON from this disaster report with fields:\n"
                    "- summary (short string)\n"
                    "- needs (list of objects with key 'code', e.g. WATER, SHELTER, MEDICAL, FOOD)\n"
                    f"Report:\n{text}"
                )
                response = client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                )
                if response and response.text:
                    # Parse JSON block if present
                    text_resp = response.text.strip()
                    if "```json" in text_resp:
                        text_resp = text_resp.split("```json")[1].split("```")[0].strip()
                    elif "```" in text_resp:
                        text_resp = text_resp.split("```")[1].split("```")[0].strip()
                    parsed = json.loads(text_resp)
                    if isinstance(parsed, dict) and "summary" in parsed and "needs" in parsed:
                        return parsed
            except Exception:
                # Fallback to rule-based extraction if API call fails or quota exceeded
                pass

        # Rule-based fallback extraction
        needs = []
        lower_text = text.lower()
        if "water" in lower_text:
            needs.append({"code": "WATER", "label": "Drinking Water"})
        if "house" in lower_text or "collapse" in lower_text or "shelter" in lower_text:
            needs.append({"code": "SHELTER", "label": "Shelter"})
        if "medical" in lower_text or "injured" in lower_text or "doctor" in lower_text:
            needs.append({"code": "MEDICAL", "label": "Medical Aid"})
        if "food" in lower_text or "ration" in lower_text:
            needs.append({"code": "FOOD", "label": "Food Supplies"})

        if not needs:
            needs.append({"code": "GENERAL", "label": "General Assistance"})

        return {
            "summary": text[:120] + ("..." if len(text) > 120 else ""),
            "needs": needs,
            "raw_text": text,
        }
