"""Regression tests for databases stamped before run-change migration insertion."""

from __future__ import annotations

import asyncio

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.ext.asyncio import create_async_engine

from deerflow.persistence.bootstrap import _get_alembic_config, _get_head_revision

pytestmark = pytest.mark.asyncio

REVISION = "0025_run_change_seq_repair"
PREVIOUS = "0024_project_documents"


async def _schema(engine) -> tuple[set[str], set[str], set[str]]:
    async with engine.connect() as connection:

        def inspect(sync_connection):
            inspector = sa.inspect(sync_connection)
            return (
                set(inspector.get_table_names()),
                {column["name"] for column in inspector.get_columns("runs")},
                {index["name"] for index in inspector.get_indexes("runs")},
            )

        return await connection.run_sync(inspect)


async def test_repair_revision_is_the_single_chain_head() -> None:
    assert _get_head_revision() == REVISION


async def test_upgrade_repairs_database_already_stamped_at_old_head(tmp_path) -> None:
    """A pre-#5405 database at 0024 skipped the later-inserted 0023 revision."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'migration.db'}")
    cfg = _get_alembic_config(engine)
    try:
        await asyncio.to_thread(command.upgrade, cfg, PREVIOUS)
        async with engine.begin() as connection:
            await connection.execute(sa.text("DROP INDEX ix_runs_user_change_seq"))
            await connection.execute(sa.text("DROP INDEX ix_runs_change_seq"))
            await connection.execute(sa.text("DROP TABLE run_change_clock"))
            await connection.execute(sa.text("ALTER TABLE runs DROP COLUMN change_seq"))
            await connection.execute(
                sa.text(
                    "INSERT INTO runs "
                    "(run_id, thread_id, user_id, status, operation_kind, metadata_json, "
                    "kwargs_json, multitask_strategy, message_count, total_input_tokens, "
                    "total_output_tokens, total_tokens, llm_call_count, lead_agent_tokens, "
                    "subagent_tokens, middleware_tokens, created_at, updated_at) "
                    "VALUES ('legacy-run', 'legacy-thread', 'legacy-user', 'pending', "
                    "'run', '{}', '{}', 'reject', 0, 0, 0, 0, 0, 0, 0, 0, "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        tables, columns, indexes = await _schema(engine)
        assert "run_change_clock" not in tables
        assert "change_seq" not in columns
        assert "ix_runs_change_seq" not in indexes
        assert "ix_runs_user_change_seq" not in indexes

        await asyncio.to_thread(command.upgrade, cfg, "head")

        tables, columns, indexes = await _schema(engine)
        assert "run_change_clock" in tables
        assert "change_seq" in columns
        assert {"ix_runs_change_seq", "ix_runs_user_change_seq"} <= indexes

        async with engine.begin() as connection:
            repaired_row = (await connection.execute(sa.text("SELECT run_id, change_seq FROM runs WHERE run_id = 'legacy-run'"))).one()
            assert repaired_row == ("legacy-run", 0)
            await connection.execute(sa.text("INSERT INTO run_change_clock (id, value) VALUES (1, 17)"))

        # The repair revision is intentionally non-destructive on downgrade,
        # and re-applying it must preserve both run data and the live clock.
        await asyncio.to_thread(command.downgrade, cfg, PREVIOUS)
        await asyncio.to_thread(command.upgrade, cfg, "head")
        async with engine.connect() as connection:
            assert (await connection.execute(sa.text("SELECT value FROM run_change_clock WHERE id = 1"))).scalar_one() == 17
    finally:
        await engine.dispose()
