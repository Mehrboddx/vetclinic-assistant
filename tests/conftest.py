import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("VETCLINIC_DATABASE_URL", "sqlite://")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from core import models  # noqa: E402,F401
from core.database import Base  # noqa: E402


@pytest.fixture
def session():
    # Set VETCLINIC_TEST_DATABASE_URL to run against a disposable Postgres database instead of SQLite.
    url = os.environ.get("VETCLINIC_TEST_DATABASE_URL", "sqlite://")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    s = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield s
    finally:
        s.close()
        Base.metadata.drop_all(engine)
        engine.dispose()
