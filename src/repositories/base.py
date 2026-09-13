"""Base repository defining standard database access patterns."""

from sqlalchemy.orm import Session


class BaseRepository:
    """Base class for all repository classes handling session lifecycle."""

    def __init__(self, session: Session) -> None:
        self.session = session
