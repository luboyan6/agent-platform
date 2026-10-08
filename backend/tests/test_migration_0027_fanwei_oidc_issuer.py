"""Migration tests for issuer-scoped OIDC identities."""

from __future__ import annotations

import importlib

import pytest
import sqlalchemy as sa
from alembic.operations import Operations
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateIndex

from deerflow.persistence import bootstrap
from deerflow.persistence.user.model import OIDC_ISSUER_SUBJECT_INDEX_NAME, UserRow

REVISION = "0027_fanwei_oidc_issuer"
PREVIOUS = "0026_mcp_task_lease_tokens"


def test_0027_joins_the_upstream_migration_chain():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == ["0034_merge_fanwei_main"]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision("0034_merge_fanwei_main").down_revision == (REVISION, "0033_batch_result_artifact")
    assert all(len(revision.revision) <= 32 for revision in script.walk_revisions())


@pytest.mark.parametrize("previous_head", [REVISION, "0033_batch_result_artifact"])
def test_both_published_heads_upgrade_without_losing_users(tmp_path, previous_head):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'merge.db'}")
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))

    def upgrade(target):
        with engine.begin() as conn:
            context = MigrationContext.configure(conn, opts={"fn": lambda revisions, context: script._upgrade_revs(target, revisions), "render_as_batch": True})
            with Operations.context(context), context.begin_transaction():
                context.run_migrations()

    try:
        upgrade(previous_head)
        with engine.begin() as conn:
            conn.execute(sa.insert(UserRow).values(id="merge-user", email="merge@example.test"))

        for _ in range(2):
            upgrade("head")
            with engine.connect() as conn:
                assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() == "0034_merge_fanwei_main"
                assert conn.execute(sa.text("SELECT email FROM users WHERE id='merge-user'")).scalar_one() == "merge@example.test"
                inspector = sa.inspect(conn)
                assert "oauth_issuer" in {column["name"] for column in inspector.get_columns("users")}
                assert "notification_deliveries" in inspector.get_table_names()
    finally:
        engine.dispose()


def test_0027_adds_issuer_column_and_partial_identity_index(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fanwei-oidc.db'}")
    migration = importlib.import_module("deerflow.persistence.migrations.versions.0027_fanwei_oidc_issuer")

    def inspect_users() -> tuple[set[str], set[str]]:
        with engine.connect() as conn:
            inspector = sa.inspect(conn)
            return ({column["name"] for column in inspector.get_columns("users")}, {index["name"] for index in inspector.get_indexes("users")})

    try:
        # Model a versioned pre-0027 users table directly. Replaying the full
        # historical chain here is unrelated to this additive migration.
        with engine.begin() as conn:
            conn.execute(sa.text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, email VARCHAR(320) NOT NULL, oauth_provider VARCHAR(32), oauth_id VARCHAR(128))"))
        columns, indexes = inspect_users()
        assert "oauth_issuer" not in columns
        assert OIDC_ISSUER_SUBJECT_INDEX_NAME not in indexes

        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        columns, indexes = inspect_users()
        assert "oauth_issuer" in columns
        assert OIDC_ISSUER_SUBJECT_INDEX_NAME in indexes

        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO users (id, email, oauth_issuer, oauth_id) VALUES ('a', 'a@example.test', 'https://oa-a.example.test', 'subject')"))
            conn.execute(sa.text("INSERT INTO users (id, email, oauth_issuer, oauth_id) VALUES ('b', 'b@example.test', 'https://oa-b.example.test', 'subject')"))
        with engine.begin() as conn, pytest.raises(IntegrityError):
            conn.execute(sa.text("INSERT INTO users (id, email, oauth_issuer, oauth_id) VALUES ('c', 'c@example.test', 'https://oa-a.example.test', 'subject')"))

        with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        columns, indexes = inspect_users()
        assert "oauth_issuer" not in columns
        assert OIDC_ISSUER_SUBJECT_INDEX_NAME not in indexes
    finally:
        engine.dispose()


def test_issuer_subject_index_is_partial_on_postgresql():
    index = next(index for index in UserRow.__table__.indexes if index.name == OIDC_ISSUER_SUBJECT_INDEX_NAME)
    ddl = str(CreateIndex(index).compile(dialect=postgresql.dialect()))

    assert "WHERE oauth_issuer IS NOT NULL AND oauth_id IS NOT NULL" in ddl


def test_fresh_orm_schema_has_issuer_column_and_index():
    assert "oauth_issuer" in UserRow.__table__.columns
    assert OIDC_ISSUER_SUBJECT_INDEX_NAME in {index.name for index in UserRow.__table__.indexes}
