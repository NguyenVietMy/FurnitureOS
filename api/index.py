"""Vercel's recognized FastAPI entrypoint."""
from .main import application as app  # noqa: F401 - Vercel discovers this ASGI export.
