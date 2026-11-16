"""TimescaleDB hypertables + continuous aggregates, pgvector, full-text search,
and append-only audit log trigger.

Every extension-specific step is guarded so the migration also runs on a plain
PostgreSQL 16 (CI / local without extensions).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-16
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AGGREGATES = {
    # name: (bucket expression)
    "candles_5m": "time_bucket(INTERVAL '5 minutes', ts)",
    "candles_15m": "time_bucket(INTERVAL '15 minutes', ts)",
    # NSE hourly bars start 09:15 IST == 03:45 UTC
    "candles_1h": "time_bucket(INTERVAL '1 hour', ts, \"offset\" => INTERVAL '45 minutes')",
    "candles_1d": "time_bucket(INTERVAL '1 day', ts, 'Asia/Kolkata')",
}
POLICIES = {
    "candles_5m": ("3 days", "1 minute", "5 minutes"),
    "candles_15m": ("7 days", "1 minute", "15 minutes"),
    "candles_1h": ("30 days", "1 minute", "1 hour"),
    "candles_1d": ("400 days", "1 hour", "1 day"),
}


def _available(bind: sa.engine.Connection) -> set[str]:
    return {r[0] for r in bind.execute(sa.text("SELECT name FROM pg_available_extensions"))}


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    available = _available(bind)

    # ---- pgvector -------------------------------------------------------------
    if "vector" in available:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")
        op.execute("ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE vector(384) USING embedding::vector")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_rag_chunks_embedding_hnsw "
            "ON rag_chunks USING hnsw (embedding vector_cosine_ops)"
        )

    # ---- full text search for hybrid (BM25-style) retrieval ---------------------
    op.execute(
        "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS tsv tsvector "
        "GENERATED ALWAYS AS (to_tsvector('english', content)) STORED"
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_rag_chunks_tsv ON rag_chunks USING gin (tsv)")

    # ---- immutable audit log ----------------------------------------------------
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only (attempted %)', TG_OP;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log")
    op.execute(
        "CREATE TRIGGER audit_log_no_mutation BEFORE UPDATE OR DELETE ON audit_log "
        "FOR EACH ROW EXECUTE FUNCTION audit_log_immutable()"
    )

    # ---- TimescaleDB --------------------------------------------------------------
    if "timescaledb" not in available:
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")
    op.execute(
        "SELECT create_hypertable('candles', 'ts', chunk_time_interval => INTERVAL '7 days', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.execute(
        "SELECT create_hypertable('option_chain_snapshots', 'ts', chunk_time_interval => INTERVAL '1 day', "
        "if_not_exists => TRUE, migrate_data => TRUE)"
    )
    op.execute(
        "ALTER TABLE candles SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'symbol, \"interval\"', timescaledb.compress_orderby = 'ts DESC')"
    )
    op.execute("SELECT add_compression_policy('candles', INTERVAL '30 days', if_not_exists => TRUE)")
    op.execute(
        "ALTER TABLE option_chain_snapshots SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'underlying, expiry')"
    )
    op.execute("SELECT add_compression_policy('option_chain_snapshots', INTERVAL '7 days', if_not_exists => TRUE)")
    op.execute("SELECT add_retention_policy('option_chain_snapshots', INTERVAL '730 days', if_not_exists => TRUE)")

    # continuous aggregates cannot be created inside a transaction block
    with op.get_context().autocommit_block():
        for name, bucket in AGGREGATES.items():
            op.execute(
                f"""
                CREATE MATERIALIZED VIEW IF NOT EXISTS {name}
                WITH (timescaledb.continuous) AS
                SELECT symbol, {bucket} AS ts,
                       first(open, ts) AS open, max(high) AS high, min(low) AS low,
                       last(close, ts) AS close, sum(volume) AS volume, last(oi, ts) AS oi
                FROM candles
                WHERE "interval" = '1m'
                GROUP BY symbol, 2
                WITH NO DATA
                """
            )
            start, end, every = POLICIES[name]
            op.execute(
                f"SELECT add_continuous_aggregate_policy('{name}', start_offset => INTERVAL '{start}', "
                f"end_offset => INTERVAL '{end}', schedule_interval => INTERVAL '{every}', if_not_exists => TRUE)"
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    available = _available(bind)
    if "timescaledb" in available:
        with op.get_context().autocommit_block():
            for name in AGGREGATES:
                op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE")
    op.execute("DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log")
    op.execute("DROP FUNCTION IF EXISTS audit_log_immutable()")
    op.execute("DROP INDEX IF EXISTS ix_rag_chunks_tsv")
    op.execute("ALTER TABLE rag_chunks DROP COLUMN IF EXISTS tsv")
    if "vector" in available:
        op.execute("DROP INDEX IF EXISTS ix_rag_chunks_embedding_hnsw")
        op.execute("ALTER TABLE rag_chunks ALTER COLUMN embedding TYPE text USING embedding::text")
