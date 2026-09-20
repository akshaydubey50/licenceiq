"""Synchronous SQLAlchemy foundation kept separate from application startup."""

from typing import Any

from sqlalchemy import MetaData, create_engine
from sqlalchemy.engine import Engine

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def create_sync_engine(database_url: str, **kwargs: Any) -> Engine:
    """Create the future durable-mode engine without activating it in ``create_app``."""
    if not database_url.startswith("postgresql+psycopg://"):
        raise ValueError("The durable database URL must use PostgreSQL with psycopg 3.")
    return create_engine(database_url, pool_pre_ping=True, **kwargs)
