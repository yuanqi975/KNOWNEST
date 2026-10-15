from collections.abc import Generator
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from .config import get_settings


class Base(DeclarativeBase):
    pass


settings = get_settings()
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables() -> None:
    from app.models import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    # The project currently uses create_all rather than Alembic migrations in
    # local deployments. Add the chunking columns for databases created by an
    # earlier version without touching existing data.
    additions = {
        "knowledge_bases": {
            "chunking_config": "JSON",
            "chunking_config_version": "INTEGER DEFAULT 1",
            "chunking_needs_reindex": "BOOLEAN DEFAULT FALSE",
        },
        "documents": {
            "chunking_config_version": "INTEGER DEFAULT 0",
        },
        "citations": {
            "retrieval_rank": "INTEGER",
        },
        "document_chunks": {
            "chunking_strategy": "VARCHAR(20)",
            "chunk_level": "VARCHAR(12) DEFAULT 'single'",
            "parent_chunk_id": "VARCHAR(36)",
        },
        "mcp_servers": {
            "status": "VARCHAR(20) DEFAULT 'disconnected'",
            "last_error": "TEXT",
            # TIMESTAMP is accepted by both SQLite and PostgreSQL. Using the
            # SQLite-only DATETIME name makes PostgreSQL startup fail when
            # upgrading an existing database.
            "connected_at": "TIMESTAMP",
            "last_discovered_at": "TIMESTAMP",
        },
        "mcp_tools": {
            "output_schema": "JSON",
            "stale": "BOOLEAN DEFAULT FALSE",
        },
    }
    inspector = inspect(engine)
    with engine.begin() as connection:
        for table, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table)}
            for name, definition in columns.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
