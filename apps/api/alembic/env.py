"""Alembic environment (async engine)."""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from algo_db import models  # noqa: F401  (register all models)
from algo_db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

if os.environ.get("DATABASE_URL"):
    config.set_main_option("sqlalchemy.url", os.environ["DATABASE_URL"])

target_metadata = Base.metadata

# Objects managed only by raw SQL in migration 0002 (extension-specific).
_MIGRATION_ONLY = {"tsv", "ix_rag_chunks_tsv", "ix_rag_chunks_embedding_hnsw"}


def include_object(obj, name, type_, reflected, compare_to):  # type: ignore[no-untyped-def]
    return name not in _MIGRATION_ONLY


def compare_type(ctx, inspected_column, metadata_column, inspected_type, metadata_type):  # type: ignore[no-untyped-def]
    if metadata_column.name == "embedding":
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=target_metadata, compare_type=compare_type,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
