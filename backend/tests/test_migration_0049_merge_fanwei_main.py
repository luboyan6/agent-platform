"""Converge both published migration heads without changing schema or data."""

from alembic.script import ScriptDirectory

from deerflow.persistence import bootstrap

REVISION = "0049_merge_fanwei_main"
PARENTS = ("0034_merge_fanwei_main", "0048_extension_execution_leases")


def test_0049_is_the_single_merge_head():
    script = ScriptDirectory(str(bootstrap._MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENTS
    assert script.get_revision(PARENTS[0]).down_revision == ("0027_fanwei_oidc_issuer", "0033_batch_result_artifact")
    assert script.get_revision(PARENTS[1]).down_revision == "0047_mcp_oauth_tokens"
    assert all(len(revision.revision) <= 32 for revision in script.walk_revisions())
