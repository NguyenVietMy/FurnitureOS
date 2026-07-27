"""Composition root.

The only place that knows the full list of modules. It mounts each module's router and
registers its models; it never reaches into module internals. Adding a module means
adding two lines here and nothing else.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

import furnitureos.registry  # noqa: F401  registers ORM models on Base.metadata
from furnitureos.modules.units import router as units_router

app = FastAPI(title="FurnitureOS API", version="0.1.0")

# The buyer app is served from a separate origin in development (Next.js on 3000,
# API on 8000). Tightened before anything ships publicly.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(units_router)


@app.get("/api/health", tags=["ops"])
def health() -> dict[str, str]:
    return {"status": "ok"}
