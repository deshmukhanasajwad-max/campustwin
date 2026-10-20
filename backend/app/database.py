import os
import time
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

def _normalize_url(url: str) -> str:
    """Hosts such as Render hand out 'postgres://' / 'postgresql://' URLs;
    SQLAlchemy needs the explicit psycopg2 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


DATABASE_URL = _normalize_url(os.getenv(
    "DATABASE_URL", "postgresql+psycopg2://campustwin:campustwin@localhost:5432/campustwin"
))

# Retry connecting a few times in case the db container is still starting up.
_engine = None
for attempt in range(15):
    try:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        conn = _engine.connect()
        conn.close()
        break
    except Exception:
        time.sleep(2)
if _engine is None:
    _engine = create_engine(DATABASE_URL, pool_pre_ping=True)

engine = _engine
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
