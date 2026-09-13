"""Pytest fixtures and test database setup."""

from collections.abc import Generator
from pathlib import Path
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from src.core.database import Base
from src.repositories.article_repository import ArticleRepository
from src.repositories.cost_repository import CostRepository
from src.repositories.render_repository import RenderRepository
from src.repositories.script_repository import ScriptRepository
from src.services.storage_service import LocalStorageService


@pytest.fixture
def test_engine():
    """In-memory SQLite database engine for testing without external servers."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        echo=False,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """Provide an isolated database session per test."""
    testing_session_local = sessionmaker(
        autocommit=False, autoflush=False, bind=test_engine
    )
    session = testing_session_local()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def cost_repo(db_session: Session) -> CostRepository:
    return CostRepository(db_session)


@pytest.fixture
def article_repo(db_session: Session) -> ArticleRepository:
    return ArticleRepository(db_session)


@pytest.fixture
def script_repo(db_session: Session) -> ScriptRepository:
    return ScriptRepository(db_session)


@pytest.fixture
def render_repo(db_session: Session) -> RenderRepository:
    return RenderRepository(db_session)


@pytest.fixture
def temp_storage(tmp_path: Path) -> LocalStorageService:
    return LocalStorageService(base_dir=tmp_path / "assets")
