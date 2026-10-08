"""Merge the published Fanwei OIDC and upstream migration branches.

Revision ID: 0034_merge_fanwei_main
Revises: 0027_fanwei_oidc_issuer, 0033_batch_result_artifact
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0034_merge_fanwei_main"
down_revision: str | Sequence[str] | None = ("0027_fanwei_oidc_issuer", "0033_batch_result_artifact")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Both parent revisions own their schema; only join the version history.
    return None


def downgrade() -> None:
    return None
