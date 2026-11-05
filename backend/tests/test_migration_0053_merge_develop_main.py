"""Both previously published migration heads retain their data after merging."""

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

from deerflow.persistence import bootstrap


@pytest.mark.parametrize("previous", ["0050_merge_published_heads", "0052_batch_continuation"])
def test_published_heads_converge_without_losing_data(previous):
    engine = sa.create_engine("sqlite://")
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))

    def upgrade(target):
        with engine.begin() as conn:
            context = MigrationContext.configure(conn, opts={"fn": lambda revisions, context: script._upgrade_revs(target, revisions), "render_as_batch": True})
            with Operations.context(context), context.begin_transaction():
                context.run_migrations()

    try:
        upgrade(previous)
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO users (id, email, system_role, created_at, needs_setup, token_version) VALUES ('merge-user', 'merge@example.test', 'user', CURRENT_TIMESTAMP, 0, 0)"))
        upgrade("head")
        upgrade("head")
        with engine.connect() as conn:
            assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0053_merge_develop_main"
            assert conn.execute(sa.text("SELECT email FROM users WHERE id='merge-user'")).scalar_one() == "merge@example.test"
            assert "oauth_issuer" in {column["name"] for column in sa.inspect(conn).get_columns("users")}
            assert "continuation_status" in {column["name"] for column in sa.inspect(conn).get_columns("subagent_batches")}
    finally:
        engine.dispose()
