from pathlib import Path
from permgraph.engine import PermGraphEngine


def test_transitive_inheritance_and_instant_revocation(tmp_path: Path):
    eng = PermGraphEngine(db_path=tmp_path / "perm_test.db")
    eng.write_tuple("org", "acme", "owner", "user", "bharath")
    eng.write_tuple("team", "sre", "member", "org", "acme", "member")
    eng.write_tuple("folder", "secrets", "editor", "team", "sre", "member")
    eng.write_tuple("doc", "prod-env", "parent", "folder", "secrets")

    allowed_res = eng.check("doc", "prod-env", "viewer", "user", "bharath")
    assert allowed_res.allowed is True
    assert len(allowed_res.path) == 4

    # Second identical check hits revision-stamped cache
    cached_res = eng.check("doc", "prod-env", "viewer", "user", "bharath")
    assert cached_res.allowed is True
    assert cached_res.cache_hit is True

    # Revoking team membership immediately bumps revision and invalidates cache
    eng.delete_tuple("team", "sre", "member", "org", "acme", "member")
    revoked_res = eng.check("doc", "prod-env", "viewer", "user", "bharath")
    assert revoked_res.allowed is False
    assert revoked_res.cache_hit is False


def test_cycle_protection(tmp_path: Path):
    eng = PermGraphEngine(db_path=tmp_path / "cycle_test.db")
    eng.write_tuple("folder", "node-a", "parent", "folder", "node-b")
    eng.write_tuple("folder", "node-b", "parent", "folder", "node-a")

    res = eng.check("folder", "node-a", "viewer", "user", "alice")
    assert res.allowed is False
