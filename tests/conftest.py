import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("OPTIMIZA_SOURCE_MODE", "demo")
os.environ.setdefault("LLM_PROVIDER", "none")
os.environ.setdefault("MASK_PII", "true")
os.environ.setdefault(
    "OPTIMIZA_DATA_DIR", os.environ.get("OPTIMIZA_TEST_DATA_DIR", str(ROOT / "backend/app/data"))
)

import pytest  # noqa: E402

from backend.app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def duck():
    from backend.app.engines.duckdb_engine import get_duckdb

    return get_duckdb()


@pytest.fixture(scope="session")
def catalog():
    from backend.app.semantic.catalog import get_catalog

    return get_catalog()
