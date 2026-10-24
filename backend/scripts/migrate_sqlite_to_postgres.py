"""Merge the legacy SQLite runtime database into PostgreSQL.

The target is intentionally not truncated. Users with the same username and
workspaces with the same owner/name are reused; all other rows keep their
legacy primary keys. Existing rows with the same primary key are skipped.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sqlalchemy import JSON, MetaData, create_engine, select
from sqlalchemy.engine import Engine


TABLE_ORDER = (
    "users",
    "workspaces",
    "knowledge_bases",
    "folders",
    "documents",
    "document_chunks",
    "ingestion_jobs",
    "chat_sessions",
    "chat_messages",
    "message_executions",
    "citations",
    "memories",
    "model_profiles",
    "mcp_servers",
    "mcp_tools",
    "request_logs",
)

TARGET_DEFAULTS = {
    ("knowledge_bases", "chunking_config_version"): 1,
    ("knowledge_bases", "chunking_needs_reindex"): False,
    ("document_chunks", "chunk_level"): "single",
    ("document_chunks", "version"): 1,
    ("document_chunks", "index_status"): "pending",
    ("mcp_servers", "enabled"): False,
    ("mcp_servers", "timeout_seconds"): 30,
    ("mcp_tools", "enabled"): False,
    ("documents", "file_size"): 0,
    ("documents", "parse_status"): "pending",
    ("ingestion_jobs", "progress"): 0,
    ("ingestion_jobs", "attempts"): 0,
}


def reflect(engine: Engine) -> MetaData:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    return metadata


def row_exists(connection, table, row: dict[str, Any]) -> bool:
    primary_key = list(table.primary_key.columns)
    if not primary_key:
        return False
    values = {column.name: row[column.name] for column in primary_key}
    return connection.execute(select(table).filter_by(**values).limit(1)).first() is not None


def migrate(source: Engine, target: Engine, dry_run: bool = False) -> dict[str, int]:
    source_meta = reflect(source)
    target_meta = reflect(target)
    source_tables = {name: source_meta.tables[name] for name in TABLE_ORDER if name in source_meta.tables}
    target_tables = {name: target_meta.tables[name] for name in TABLE_ORDER if name in target_meta.tables}
    stats = {name: 0 for name in source_tables}
    skipped = {name: 0 for name in source_tables}
    user_map: dict[str, str] = {}
    workspace_map: dict[str, str] = {}

    with source.connect() as source_connection, target.begin() as target_connection:
        # Resolve natural identities first, so all dependent rows point to the
        # existing PostgreSQL account/workspace when one is already present.
        if "users" in source_tables and "users" in target_tables:
            target_users = {
                row.username: row.id
                for row in target_connection.execute(select(target_tables["users"].c.username, target_tables["users"].c.id))
            }
            for row in source_connection.execute(select(source_tables["users"])):
                values = dict(row._mapping)
                user_map[values["id"]] = target_users.get(values["username"], values["id"])

        if "workspaces" in source_tables and "workspaces" in target_tables:
            target_workspaces = {
                (row.owner_id, row.name): row.id
                for row in target_connection.execute(select(target_tables["workspaces"].c.owner_id, target_tables["workspaces"].c.name, target_tables["workspaces"].c.id))
            }
            for row in source_connection.execute(select(source_tables["workspaces"])):
                values = dict(row._mapping)
                owner_id = user_map.get(values["owner_id"], values["owner_id"])
                workspace_map[values["id"]] = target_workspaces.get((owner_id, values["name"]), values["id"])

        if dry_run:
            return stats

        for name, source_table in source_tables.items():
            target_table = target_tables.get(name)
            if target_table is None:
                continue
            target_columns = {column.name for column in target_table.columns}
            for source_row in source_connection.execute(select(source_table)):
                values = {key: value for key, value in source_row._mapping.items() if key in target_columns}
                for column in target_table.columns:
                    if column.name not in values or values[column.name] is None:
                        fallback = TARGET_DEFAULTS.get((name, column.name))
                        if fallback is not None:
                            values[column.name] = fallback
                    if column.name in values and isinstance(column.type, JSON) and isinstance(values[column.name], str):
                        if values[column.name] == "null":
                            values[column.name] = None
                        else:
                            try:
                                values[column.name] = json.loads(values[column.name])
                            except json.JSONDecodeError:
                                pass
                if name == "users" and values.get("id") in user_map:
                    mapped_id = user_map[values["id"]]
                    if mapped_id != values["id"]:
                        skipped[name] += 1
                        continue
                if name == "workspaces":
                    values["owner_id"] = user_map.get(values.get("owner_id"), values.get("owner_id"))
                    if values.get("id") in workspace_map:
                        mapped_id = workspace_map[values["id"]]
                        if mapped_id != values["id"]:
                            skipped[name] += 1
                            continue
                if "user_id" in values:
                    values["user_id"] = user_map.get(values["user_id"], values["user_id"])
                if "owner_id" in values:
                    values["owner_id"] = user_map.get(values["owner_id"], values["owner_id"])
                if "workspace_id" in values:
                    values["workspace_id"] = workspace_map.get(values["workspace_id"], values["workspace_id"])
                if row_exists(target_connection, target_table, values):
                    skipped[name] += 1
                    continue
                target_connection.execute(target_table.insert().values(**values))
                stats[name] += 1

    for name in stats:
        print(f"{name}: migrated={stats[name]} skipped={skipped[name]}")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("knownest-local.db"))
    parser.add_argument("--target", default="postgresql+psycopg://knownest:knownest@localhost:5432/knownest")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.source.exists():
        raise SystemExit(f"SQLite database not found: {args.source}")
    source = create_engine(f"sqlite:///{args.source.resolve().as_posix()}")
    target = create_engine(args.target, pool_pre_ping=True)
    migrate(source, target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
