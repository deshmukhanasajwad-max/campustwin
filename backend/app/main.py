import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text
from .database import engine, Base, SessionLocal
from . import models  # noqa: F401  (ensures models are registered on Base)
from . import seed_data
from .routers import auth, resources, bookings, analytics, predictions, alerts, reports, timetables, insights

app = FastAPI(title="CampusTwin API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _migrate():
    """create_all() never alters existing tables, so databases created by an
    earlier version of CampusTwin (e.g. a persisted Docker volume) get the new
    booking columns added here. Safe to run on every start."""
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'manual'"))
        conn.execute(text("ALTER TABLE bookings ADD COLUMN IF NOT EXISTS timetable_entry_id INTEGER"))
        conn.execute(text("UPDATE bookings SET source='manual' WHERE source IS NULL"))


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _migrate()
    if os.getenv("SEED_ON_START", "true").lower() == "true":
        db = SessionLocal()
        try:
            if seed_data.needs_seed(db):
                seed_data.seed(db)
            else:
                print("[startup] database already seeded, skipping.")
        finally:
            db.close()


app.include_router(auth.router)
app.include_router(resources.router)
app.include_router(bookings.router)
app.include_router(analytics.router)
app.include_router(predictions.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(timetables.router)
app.include_router(insights.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Serve the frontend (index.html + app.js) at the root path.
# Mounted last so it doesn't shadow the /api/* routes above.
def _find_frontend_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.getenv("FRONTEND_DIR", ""),
        os.path.join(here, "..", "frontend"),        # Docker layout: /app/frontend
        os.path.join(here, "..", "..", "frontend"),  # repo layout: backend/app -> ../../frontend
    ]
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "index.html")):
            return os.path.abspath(c)
    raise RuntimeError("frontend/index.html not found; set FRONTEND_DIR")


app.mount("/", StaticFiles(directory=_find_frontend_dir(), html=True), name="frontend")
