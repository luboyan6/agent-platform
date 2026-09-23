"""Add verified issuer mapping for OIDC accounts.

Revision ID: 0027_fanwei_oidc_issuer
Revises: 0026_mcp_task_lease_tokens
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027_fanwei_oidc_issuer"
down_revision: str | Sequence[str] | None = "0026_mcp_task_lease_tokens"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column("users", sa.Column("oauth_issuer", sa.String(length=512), nullable=True))
    inspector = sa.inspect(op.get_bind())
    if "idx_users_oidc_issuer_subject" not in {index["name"] for index in inspector.get_indexes("users")}:
        op.create_index(
            "idx_users_oidc_issuer_subject",
            "users",
            ["oauth_issuer", "oauth_id"],
            unique=True,
            sqlite_where=sa.text("oauth_issuer IS NOT NULL AND oauth_id IS NOT NULL"),
            postgresql_where=sa.text("oauth_issuer IS NOT NULL AND oauth_id IS NOT NULL"),
        )


def downgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_drop_column

    inspector = sa.inspect(op.get_bind())
    if "idx_users_oidc_issuer_subject" in {index["name"] for index in inspector.get_indexes("users")}:
        op.drop_index("idx_users_oidc_issuer_subject", table_name="users")
    safe_drop_column("users", "oauth_issuer")
