"""Sentinel configuration: secrets come from .env, monitoring targets are defined here."""

import os

from dotenv import load_dotenv

load_dotenv()

RENDER_API_KEY = os.getenv("RENDER_API_KEY")
RENDER_SERVICE_ID = os.getenv("RENDER_SERVICE_ID")  # looks like srv-xxxxxxxxxxxx
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")

# Name -> URL. Confirm these match your live URLs exactly.
HTTP_TARGETS = {
    "PD-Voice-Screening API": "https://pd-voice-screening.onrender.com/health",
    # /stats queries Neon, so a healthy response proves Render + API code + database work end to end.
    "PD-Voice-Screening DB via API (Neon)": "https://pd-voice-screening.onrender.com/stats",
    "PD-Voice-Screening UI": "https://pd-voice-screening-baffxyy.streamlit.app",
    "MedRAG UI": "https://medrag-baffxy.streamlit.app",
}

# Which GitHub repo should receive an issue when a given target fails.
TARGET_REPOS = {
    "PD-Voice-Screening API": "Baffxy/PD-Voice-Screening",
    "PD-Voice-Screening API (Render)": "Baffxy/PD-Voice-Screening",
    "PD-Voice-Screening DB via API (Neon)": "Baffxy/PD-Voice-Screening",
    "PD-Voice-Screening UI": "Baffxy/PD-Voice-Screening",
    "MedRAG UI": "Baffxy/MedRAG",
}
