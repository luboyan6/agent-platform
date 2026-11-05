"""Converge both published migration heads without changing schema or data."""

from alembic.script import ScriptDirectory

from deerflow.persistence import bootstrap

REVISION = "0049_merge_fanwei_main"
PARENTS = ("0034_merge_fanwei_main", "0048_extension_execution_leases")


def test_0050_preserves_both_published_merge_histories():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == ["0053_merge_develop_main"]
    assert script.get_revision("0053_merge_develop_main").down_revision == ("0050_merge_published_heads", "0052_batch_continuation")
    assert script.get_revision("0050_merge_published_heads").down_revision == ("0047_merge_fanwei_main", REVISION)
    assert script.get_revision(REVISION).down_revision == PARENTS
    assert script.get_revision(PARENTS[0]).down_revision == ("0027_fanwei_oidc_issuer", "0033_batch_result_artifact")
    assert script.get_revision(PARENTS[1]).down_revision == "0047_mcp_oauth_tokens"
    assert all(len(revision.revision) <= 32 for revision in script.walk_revisions())
