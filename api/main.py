from __future__ import annotations
from fastapi import FastAPI
try:
    from api.routes import app as routes_app  # type: ignore
    app = routes_app
except Exception:
    app = FastAPI()
    from api.routes import router as routes_router  # type: ignore
    app.include_router(routes_router)
from api.baseline_router import router as baseline_router
app.include_router(baseline_router)
