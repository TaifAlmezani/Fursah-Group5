"""Shared pytest fixtures for the FURSAH backend.

No live model is ever called: every fixture builds dependencies with model_config=None, so
the deterministic path is exercised. The one LLM test mocks the client directly.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

# Make `import app` work no matter where pytest is invoked from.
sys.path.insert(0, os.path.dirname(__file__))

from app.infrastructure.config import get_settings
from app.infrastructure.data_package import DatasetLoader
from app.infrastructure.dependencies import AppDependencies
from app.infrastructure.tracing import Tracer
from app.repository import OpportunityRepository

# The classroom evaluation instant (noon, Riyadh) — fixed so deadline tests are deterministic.
EVAL_TIME = datetime(2026, 10, 18, 12, 0, 0, tzinfo=timezone(timedelta(hours=3)))


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture()
def repo(settings) -> OpportunityRepository:
    return OpportunityRepository(DatasetLoader(settings))


@pytest.fixture()
def deps(settings, repo) -> AppDependencies:
    return AppDependencies(
        settings=settings,
        bridge=repo.bridge,
        repository=repo,
        model_config=None,  # keyless: deterministic workflow path
        tracer=Tracer(),
        evaluation_time=EVAL_TIME,
    )


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient
    from app.main import app

    return TestClient(app)
