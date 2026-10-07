"""Database engine and session lifecycle management."""

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from src.core.config import settings


class Base(DeclarativeBase):
    """Base declarative class for all SQLAlchemy ORM entities."""

    pass


def build_engine(database_url: str | None = None):
    """Construct SQLAlchemy engine with appropriate dialect arguments.

    SQLite requires disabling thread checking for concurrent CLI tasks.
    PostgreSQL uses connection pooling with pre-ping validation.
    """
    url = database_url or settings.database_url
    # SQLAlchemy 2.x defaults bare "postgresql://" to psycopg (v3).
    # Also handle "postgres://" schemes commonly provided by Supabase.
    # This project ships psycopg2-binary, so pin the dialect explicitly.
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+psycopg2://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg2://", 1)
    connect_args: dict[str, Any] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 30
        eng = create_engine(url, connect_args=connect_args, echo=False)

        @event.listens_for(eng, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=30000")
            finally:
                cursor.close()

        return eng

    return create_engine(
        url,
        pool_pre_ping=True,
        pool_recycle=300,
        pool_size=10,
        max_overflow=20,
        echo=False,
    )


engine = build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db(target_engine=None) -> None:
    """Initialize database tables and extensions.

    Conditionally installs the pgvector extension when connecting to PostgreSQL.
    Creates all tables declared in ORM models.
    """
    active_engine = target_engine or engine
    url_str = str(active_engine.url)

    if "postgresql" in url_str:
        with active_engine.connect() as conn:
            try:
                conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                conn.commit()
            except Exception:
                pass

    Base.metadata.create_all(bind=active_engine)

    if "sqlite" in url_str:
        with active_engine.connect() as conn:
            try:
                res_scripts = conn.execute(text("PRAGMA table_info(scripts)")).fetchall()
                if res_scripts:
                    col_names = [r[1] for r in res_scripts]
                    if "cluster_ids" not in col_names:
                        conn.execute(
                            text("ALTER TABLE scripts ADD COLUMN cluster_ids JSON DEFAULT '[]'")
                        )
                        conn.commit()

                res_clusters = conn.execute(text("PRAGMA table_info(story_clusters)")).fetchall()
                if res_clusters:
                    cluster_cols = [r[1] for r in res_clusters]
                    if "cluster_run_id" not in cluster_cols:
                        conn.execute(
                            text(
                                "ALTER TABLE story_clusters "
                                "ADD COLUMN cluster_run_id VARCHAR(64) DEFAULT 'run_default'"
                            )
                        )
                    if "run_cluster_index" not in cluster_cols:
                        conn.execute(
                            text(
                                "ALTER TABLE story_clusters "
                                "ADD COLUMN run_cluster_index INTEGER DEFAULT 1"
                            )
                        )
                    conn.commit()
            except Exception:
                pass
    elif "postgresql" in url_str:
        with active_engine.connect() as conn:
            try:
                conn.execute(
                    text(
                        "ALTER TABLE story_clusters "
                        "ADD COLUMN IF NOT EXISTS cluster_run_id VARCHAR(64) DEFAULT 'run_default'"
                    )
                )
                conn.execute(
                    text(
                        "ALTER TABLE story_clusters "
                        "ADD COLUMN IF NOT EXISTS run_cluster_index INTEGER DEFAULT 1"
                    )
                )
                conn.commit()
            except Exception:
                pass


@contextmanager
def get_session() -> Generator[Session, None, None]:
    """Provide a transactional database session scope.

    Commits on successful block exit, rolls back on uncaught exception,
    and reliably closes the session.
    """
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
