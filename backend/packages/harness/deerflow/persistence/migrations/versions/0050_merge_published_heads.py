"""Merge both published Fanwei migration histories.

Revision ID: 0050_merge_published_heads
Revises: 0047_merge_fanwei_main, 0049_merge_fanwei_main
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0050_merge_published_heads"
down_revision: str | Sequence[str] | None = ("0047_merge_fanwei_main", "0049_merge_fanwei_main")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical parents own their schema; only join their version rows.
    return None


def downgrade() -> None:
    return None
