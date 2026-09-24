"""
embedding_utils.py
------------------
Utility for generating L2-normalised text embeddings via the Gemini API.

Model   : gemini-embedding-001
Dims    : 768
Task    : SEMANTIC_SIMILARITY
Config  : GEMINI_API_KEY read from .env in the project root.
          The key is NEVER printed, logged, or stored anywhere.

Usage
-----
    from database.scripts.embedding_utils import embed_text

    vector = embed_text("Families need drinking water near the school.")
    # vector is a list[float] of length 768, L2-normalised.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from dotenv import load_dotenv

# ------------------------------------------------------------------ #
# Load credentials from the project-root .env (two levels up from    #
# database/scripts/).  Never hard-code or print the key.             #
# ------------------------------------------------------------------ #
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=_ENV_PATH, override=False)

_API_KEY = os.environ.get("GEMINI_API_KEY")
if not _API_KEY:
    raise EnvironmentError(
        "GEMINI_API_KEY not found. "
        "Add it to the .env file at the project root."
    )

# Lazy import so the module can be imported without google-genai installed
# during unit-testing with a stub.
try:
    from google import genai
    from google.genai import types as genai_types
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "google-genai is required. Install it with:\n"
        "  pip install google-genai"
    ) from exc

# Build the client once at module load (re-used across calls).
_CLIENT = genai.Client(api_key=_API_KEY)
_MODEL   = "gemini-embedding-001"
_DIMS    = 768


def _l2_normalise(vec: list[float]) -> list[float]:
    """Return a unit-length copy of *vec* (L2 norm = 1.0)."""
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0.0:
        return vec  # zero vector — return as-is to avoid division by zero
    return [v / norm for v in vec]


def embed_text(text: str) -> list[float]:
    """
    Embed *text* with Gemini gemini-embedding-001 and return a
    768-dimensional, L2-normalised vector.

    Parameters
    ----------
    text : str
        The plain-text content to embed.  Must be non-empty.

    Returns
    -------
    list[float]
        A list of 768 floats with ||v||₂ = 1.0.

    Raises
    ------
    ValueError
        If *text* is empty.
    google.genai.errors.APIError
        On Gemini API failures (rate limit, quota, etc.).
    """
    if not text or not text.strip():
        raise ValueError("embed_text: text must be a non-empty string.")

    response = _CLIENT.models.embed_content(
        model=_MODEL,
        contents=text,
        config=genai_types.EmbedContentConfig(
            task_type="SEMANTIC_SIMILARITY",
            output_dimensionality=_DIMS,
        ),
    )

    raw_vector: list[float] = response.embeddings[0].values
    return _l2_normalise(raw_vector)
