"""The pgserver seeding helper must fail AT the broken statement.

``pgserver``'s ``psql()`` keeps going after a SQL error and exits 0, so a seed
script that half-worked returns cleanly and the test fails much later on an
assertion about rows that were never inserted. These tests pin the fixed
behaviour of ``tests.conftest.psql_strict`` against a real Postgres, using the
exact failure that caused the problem: a NOT NULL violation.

The first test also documents the ORIGINAL behaviour rather than only asserting
the new one — if a future pgserver release starts failing loudly on its own,
that test goes red and tells us this wrapper is redundant, instead of the
wrapper silently outliving its reason to exist.
"""

import os
import subprocess
import tempfile
from pathlib import Path

import pytest

from app.core.config import get_settings
from tests.conftest import PsqlSeedError, psql_strict


@pytest.fixture(scope="module")
def cluster():
    """Ephemeral in-process Postgres with one NOT NULL table to violate."""
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = Path(tempfile.mkdtemp(prefix="ittu-pgdata-psql-"))/"pg"
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    srv.psql("CREATE TABLE seed_target (id int NOT NULL, note text);")
    yield srv
    srv.cleanup()


@pytest.fixture
def fresh_cluster():
    """A cluster of its own, with NO migrations and no seed table.

    Function-scoped and separate from `cluster` on purpose: the two tests below
    either migrate the database or depend on the schemas being absent, and doing
    that to the shared module-scoped cluster would leak state into every other
    test in this file.
    """
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = Path(tempfile.mkdtemp(prefix="ittu-pgdata-fresh-")) / "pg"
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")
    yield srv
    srv.cleanup()


def test_plain_psql_still_swallows_the_error(cluster):
    """The behaviour psql_strict exists to fix, pinned as a fact.

    Not a test of our code — a test of the assumption our code rests on. If
    pgserver ever starts raising here, psql_strict's wrapper is redundant and
    this red test is how we find out.
    """
    out = cluster.psql("INSERT INTO seed_target (id) VALUES (NULL);")
    assert out == "", (
        "pgserver.psql() now returns something on a failed statement — re-check "
        "whether psql_strict is still needed"
    )


def test_plain_psql_does_not_even_abort_the_rest_of_the_script(cluster):
    """The worse half: a failed statement does not stop the ones after it.

    This is why the symptom was so confusing — the database ends up
    HALF-seeded, so the eventual failure looks like a data mismatch rather than
    a setup error.
    """
    cluster.psql(
        "INSERT INTO seed_target (id, note) VALUES (NULL, 'first');"
        "INSERT INTO seed_target (id, note) VALUES (1, 'second');"
    )
    got = cluster.psql("SELECT count(*) FROM seed_target WHERE note = 'second';")
    assert "1" in got, "expected the statement AFTER the failing one to have run"


def test_psql_strict_raises_at_the_broken_statement(cluster):
    """THE fix: the same seed now fails immediately, not three assertions later."""
    with pytest.raises(PsqlSeedError) as excinfo:
        psql_strict(cluster, "INSERT INTO seed_target (id) VALUES (NULL);")

    message = str(excinfo.value)
    assert "INSERT INTO seed_target" in message, "the failing SQL is not named"
    assert "Captured stderr" in message, "the reader is not told where Postgres's message is"
    assert isinstance(excinfo.value.__cause__, subprocess.CalledProcessError)


def test_psql_strict_aborts_before_the_later_statements(cluster):
    """ON_ERROR_STOP also fixes the half-seeded database: nothing after the
    failing statement runs, so the fixture cannot leave partial state behind."""
    with pytest.raises(PsqlSeedError):
        psql_strict(
            cluster,
            "INSERT INTO seed_target (id, note) VALUES (NULL, 'aborted-first');"
            "INSERT INTO seed_target (id, note) VALUES (2, 'should-not-exist');",
        )

    got = cluster.psql("SELECT count(*) FROM seed_target WHERE note = 'should-not-exist';")
    assert "0" in got, "a statement after the failing one still ran — ON_ERROR_STOP is not applied"


def test_psql_strict_label_names_the_fixture(cluster):
    """``label`` lets a fixture say which seed broke when a file has several."""
    with pytest.raises(PsqlSeedError, match="seeded_both_modes"):
        psql_strict(
            cluster,
            "INSERT INTO seed_target (id) VALUES (NULL);",
            label="seeded_both_modes",
        )


def test_psql_strict_is_transparent_when_the_sql_is_fine(cluster):
    """Valid SQL behaves exactly as before, output included — the wrapper must
    not change the success path, or call sites that read the result break."""
    psql_strict(cluster, "INSERT INTO seed_target (id, note) VALUES (42, 'ok');")
    out = psql_strict(cluster, "SELECT note FROM seed_target WHERE id = 42;")
    assert "ok" in out


def test_the_real_role_script_survives_strict_mode(fresh_cluster):
    """``create_app_role.sql`` in its DOCUMENTED order: migrations first.

    The script is deliberately idempotent — guarded `\\if`/`\\gset`, naturally
    idempotent GRANTs — and is re-run after every migration, so making the
    helper strict would be a silent breakage if those guards turned out to be
    error-swallowing rather than real guards. They are real: it passes on a
    migrated database, and again on re-run.
    """
    import alembic.command
    from alembic.config import Config

    backend_dir = Path(__file__).resolve().parents[1]
    owner_uri = fresh_cluster.get_uri()
    prior = {k: os.environ.get(k) for k in ("ITTU_DATABASE_URL", "ITTU_MIGRATION_DATABASE_URL")}
    async_uri = owner_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    os.environ["ITTU_DATABASE_URL"] = async_uri
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = async_uri
    get_settings.cache_clear()
    try:
        cfg = Config(str(backend_dir / "alembic.ini"))
        cfg.set_main_option("script_location", str(backend_dir / "migrations"))
        alembic.command.upgrade(cfg, "head")

        script = (backend_dir / "scripts" / "create_app_role.sql").read_text()
        payload = "\\set app_role_password 'ittu-test-role-pw-psql'\n" + script
        psql_strict(fresh_cluster, payload, label="create_app_role.sql (migrated)")
        psql_strict(fresh_cluster, payload, label="create_app_role.sql (re-run)")
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()


def test_the_role_script_refuses_to_run_before_migrations(fresh_cluster):
    """Running the role script BEFORE migrations must FAIL, not half-succeed.

    This is the bug the script's own ON_ERROR_STOP exists to prevent, and it is
    not hypothetical: every GRANT names a schema migrations create, psql's
    default is to continue after an error and still exit 0, so an out-of-order
    run produced a role with NO grants and no complaint. The app then connects
    successfully and dies at the first query with `InsufficientPrivilege`,
    pointing nowhere near the cause — which is how the missing `casedata`
    grants reached production (docs/Deploy.md §5).

    Uses plain `cluster.psql`, NOT `psql_strict`: the point is that the SCRIPT
    now protects an operator running it by hand, without our test helper.
    """
    import subprocess

    backend_dir = Path(__file__).resolve().parents[1]
    script = (backend_dir / "scripts" / "create_app_role.sql").read_text()
    payload = "\\set app_role_password 'ittu-test-role-pw-psql'\n" + script

    with pytest.raises(subprocess.CalledProcessError) as exc:
        fresh_cluster.psql(payload)

    assert exc.value.returncode != 0, (
        "the role script ran to completion against a database with no schemas — "
        "it would have created a role with no grants and reported success"
    )
