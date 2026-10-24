from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from app.core.db import engine


def upgrade_database():
    config = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    with engine.begin() as connection:
        if connection.dialect.name == "postgresql":
            # Serialize application startup migrations across processes/replicas.
            connection.execute(text("SELECT pg_advisory_xact_lock(73201514)"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
