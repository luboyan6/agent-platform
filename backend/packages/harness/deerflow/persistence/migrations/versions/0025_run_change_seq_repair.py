"""Repair run-change schema skipped by databases already stamped at 0024.

Revision ID: 0025_run_change_seq_repair
Revises: 0024_project_documents

``0023_run_change_seq`` was inserted behind revisions that had already shipped.
Alembic correctly treated databases stamped at the former 0024 head as current,
so those deployments never ran the inserted revision.  Repeat its idempotent
schema work at a new head that every such database must traverse.

This is the historical revision shipped by the pre-merge development branch.
Keep it in the graph so databases already stamped with this ID can converge
through ``0026_merge_run_change_seq`` instead of being rejected as unknown.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0025_run_change_seq_repair"
down_revision: str | Sequence[str] | None = "0024_project_documents"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    from deerflow.persistence.migrations._helpers import safe_add_column

    safe_add_column(
        "runs",
        sa.Column("change_seq", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
    )

    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "run_change_clock" not in tables:
        op.create_table(
            "run_change_clock",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("value", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
        )

    if "runs" not in tables:
        return
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes("runs")}
    if "ix_runs_change_seq" not in indexes:
        op.create_index("ix_runs_change_seq", "runs", ["change_seq", "run_id"])
    if "ix_runs_user_change_seq" not in indexes:
        op.create_index("ix_runs_user_change_seq", "runs", ["user_id", "change_seq", "run_id"])


def downgrade() -> None:
    # 0023_run_change_seq owns this schema in the canonical chain. Downgrading
    # only the repair marker to 0024 must not remove objects required by 0024.
    return None
