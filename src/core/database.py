"""Database engine and session lifecycle management."""

from collections.abc import Generator
from contextlib import contextmanager

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
    connect_args = {}
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
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()

    Base.metadata.create_all(bind=active_engine)

    if "sqlite" in url_str:
        with active_engine.connect() as conn:
            try:
                res = conn.execute(text("PRAGMA table_info(scripts)")).fetchall()
                if res:
                    col_names = [r[1] for r in res]
                    if "cluster_ids" not in col_names:
                        conn.execute(text("ALTER TABLE scripts ADD COLUMN cluster_ids JSON DEFAULT '[]'"))
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
