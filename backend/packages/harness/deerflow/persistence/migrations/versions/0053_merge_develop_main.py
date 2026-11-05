"""Join the published develop and main migration heads without schema changes."""

revision = "0053_merge_develop_main"
down_revision = ("0050_merge_published_heads", "0052_batch_continuation")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
