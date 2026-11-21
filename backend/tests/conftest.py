import os
import sys
import tempfile
from pathlib import Path

# Tests run on a throw-away SQLite file so no PostgreSQL is needed.
_db = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{_db}"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    from database import Base, engine
    from main import app

    Base.metadata.drop_all(bind=engine)
    with TestClient(app) as c:   # runs lifespan: create tables + seed
        yield c
