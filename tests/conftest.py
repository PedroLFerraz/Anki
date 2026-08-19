"""Shared fixtures for the test suite."""
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    """Every test gets its own temporary SQLite database."""
    db_path = str(tmp_path / "test.db")
    monkeypatch.setattr("core.config.settings.db_path", db_path)

    # Re-initialise the schema in the temp DB
    from storage.database import init_db
    init_db()

    yield db_path


@pytest.fixture
def media_dir(tmp_path, monkeypatch):
    """Temporary media directory for image tests."""
    md = tmp_path / "media"
    md.mkdir()
    monkeypatch.setattr("core.config.MEDIA_DIR", md)
    return md


@pytest.fixture
def exports_dir(tmp_path, monkeypatch):
    """Temporary exports directory for export tests."""
    ed = tmp_path / "exports"
    ed.mkdir()
    monkeypatch.setattr("core.config.EXPORTS_DIR", ed)
    return ed
