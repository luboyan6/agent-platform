"""Merge the published Fanwei OIDC and upstream Skill host branches.

Revision ID: 0047_merge_fanwei_main
Revises: 0034_merge_fanwei_main, 0046_skill_mutations
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0047_merge_fanwei_main"
down_revision: str | Sequence[str] | None = ("0034_merge_fanwei_main", "0046_skill_mutations")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical parents own their schema; only join their version rows.
    return None


def downgrade() -> None:
    return None
