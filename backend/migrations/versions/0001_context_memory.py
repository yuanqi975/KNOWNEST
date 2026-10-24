"""Adopt legacy databases and install context/memory storage without data loss."""
from alembic import op
import sqlalchemy as sa

revision = "0001_context_memory"
down_revision = None
branch_labels = depends_on = None


def upgrade():
    from app.core.db import Base, create_tables
    from app.models import models
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    create_tables(bind)
    additions = {
        "chat_sessions": [sa.Column("next_sequence", sa.Integer, nullable=False, server_default="1"),
                          sa.Column("context_version", sa.Integer, nullable=False, server_default="1")],
        "chat_messages": [sa.Column("sequence", sa.Integer), sa.Column("run_id", sa.String(36)),
                          sa.Column("status", sa.String(20), nullable=False, server_default="completed"), sa.Column("token_count", sa.Integer)],
        "memories": [sa.Column("knowledge_base_id", sa.String(36)), sa.Column("source_type", sa.String(20), nullable=False, server_default="manual"),
                     sa.Column("version", sa.Integer, nullable=False, server_default="1"), sa.Column("expires_at", sa.DateTime(timezone=True)),
                     sa.Column("fingerprint", sa.String(64)), sa.Column("superseded_by", sa.String(36)),
                     sa.Column("replaces_id", sa.String(36)), sa.Column("conflict_version", sa.Integer), sa.Column("subject", sa.String(160))],
        "model_profiles": [sa.Column("context_window_tokens", sa.Integer, nullable=False, server_default="32768"),
                           sa.Column("max_output_tokens", sa.Integer, nullable=False, server_default="4096")],
    }
    for table, columns in additions.items():
        existing = {c["name"] for c in sa.inspect(bind).get_columns(table)}
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)
    # Deterministic ordering for old timestamp ties. New messages use locked counters.
    op.execute("""WITH numbered AS (
        SELECT id, ROW_NUMBER() OVER (PARTITION BY session_id ORDER BY created_at, id) AS n
        FROM chat_messages)
        UPDATE chat_messages SET sequence = (SELECT n FROM numbered WHERE numbered.id = chat_messages.id)
        WHERE sequence IS NULL""")
    op.execute("""UPDATE chat_sessions SET next_sequence =
        COALESCE((SELECT MAX(sequence) + 1 FROM chat_messages WHERE session_id = chat_sessions.id), 1)""")
    indexes = {i["name"] for i in sa.inspect(bind).get_indexes("chat_messages")}
    constraints = {i["name"] for i in sa.inspect(bind).get_unique_constraints("chat_messages")}
    if "uq_message_sequence" not in indexes | constraints:
        op.create_index("uq_message_sequence", "chat_messages", ["session_id", "sequence"], unique=True)
    for table in Base.metadata.sorted_tables:
        if table.name not in additions:
            table.create(bind, checkfirst=True)
    for table, name, cols in [
        ("chat_messages", "ix_chat_messages_run_id", ["run_id"]),
        ("memories", "ix_memory_scope", ["user_id", "workspace_id", "knowledge_base_id", "status"]),
        ("memories", "ix_memories_fingerprint", ["fingerprint"]),
    ]:
        if name not in {i["name"] for i in sa.inspect(bind).get_indexes(table)}:
            op.create_index(name, table, cols)
    if bind.dialect.name == "postgresql":
        fks = sa.inspect(bind).get_foreign_keys("memories")
        if not any(fk["constrained_columns"] == ["knowledge_base_id"] for fk in fks):
            op.create_foreign_key("fk_memory_kb", "memories", "knowledge_bases", ["knowledge_base_id"], ["id"], ondelete="CASCADE")
    # Backfill vectors only; never infer memories from historical conversations.
    import hashlib, json, uuid
    rows = bind.execute(sa.text("SELECT id, user_id, workspace_id, content, version, status FROM memories"))
    for row in rows:
        fp = hashlib.sha256(" ".join(row.content.lower().split()).encode()).hexdigest()
        bind.execute(sa.text("UPDATE memories SET fingerprint=:fp WHERE id=:id"), {"fp": fp, "id": row.id})
        if row.status == "active":
            bind.execute(models.BackgroundJob.__table__.insert().values(
                id=str(uuid.uuid4()), workspace_id=row.workspace_id, memory_id=row.id,
                dedupe_key=f"embed:{row.id}:{row.version}", kind="embed",
                payload={"user_id": row.user_id, "version": row.version, "epoch": 1}, status="pending", attempts=0))


def downgrade():
    raise RuntimeError("This migration preserves user data. Roll back with feature flags, not destructive downgrade.")
