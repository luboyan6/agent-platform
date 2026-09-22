"""Merge the two published run-change repair revision IDs.

Revision ID: 0026_merge_run_change_seq
Revises: 0025_run_change_seq_repair, 0025_repair_run_change_seq

The pre-merge development branch shipped ``0025_run_change_seq_repair`` while
main independently shipped ``0025_repair_run_change_seq``. Both revisions
perform the same guarded repair after ``0024_project_documents``. Keeping both
branches and merging them lets an existing database upgrade through Alembic's
normal migration path without manually rewriting ``alembic_version``.

Alembic's default version table stores IDs in ``VARCHAR(32)``. This identifier
is deliberately 25 characters long so PostgreSQL can stamp the merge head.
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0026_merge_run_change_seq"
down_revision: str | Sequence[str] | None = ("0025_run_change_seq_repair", "0025_repair_run_change_seq")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The two parent revisions own identical, idempotent guarded DDL. This
    # merge only collapses their Alembic version rows into one new head.
    return None


def downgrade() -> None:
    # Neither parent repair owns the underlying 0023 schema, so there is no
    # schema work when stepping back to either branch.
    return None
