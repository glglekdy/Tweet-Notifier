from pathlib import Path

from miniyatcho.features.twitter.accounts import ClientPool, pick_client, unwatch, watch
from tests.fakes import FakeApp


def make_pool(tmp_path, tokens, **kw_by_name):
    def factory(path):
        return FakeApp(path, **kw_by_name.get(Path(path).name, {}))
    return ClientPool(tokens, tmp_path, factory=factory, retry_delay=0)


def test_pick_client():
    assert pick_client(["a", "b", "c"], {"a": 2, "b": 1}) == "c"
    assert pick_client(["a", "b"], {"a": 1, "b": 1}) == "a"
    assert pick_client([], {}) is None


async def test_reuses_session_when_token_matches(tmp_path):
    pool = make_pool(tmp_path, (("a", "T"),), a=dict(saved_token="T"))
    await pool.login_all()
    app = pool.states["a"].app
    assert pool.ok_names() == ["a"]
    assert app.calls == [("connect",)]
    assert app.path == str(tmp_path / "a")


async def test_relogins_when_token_changed(tmp_path):
    pool = make_pool(tmp_path, (("a", "NEW"),), a=dict(saved_token="OLD"))
    await pool.login_all()
    assert pool.states["a"].app.calls == [("load", "NEW")]


async def test_login_retries_once_then_succeeds(tmp_path):
    pool = make_pool(tmp_path, (("a", "T"),), a=dict(login_errors=1))
    await pool.login_all()
    assert pool.states["a"].ok


async def test_failed_client_does_not_stop_others(tmp_path):
    pool = make_pool(tmp_path, (("a", "T"), ("b", "T")), a=dict(login_errors=2), b=dict())
    await pool.login_all()
    assert pool.ok_names() == ["b"]
    assert pool.states["a"].error


async def test_watch_unwatch_order():
    app = FakeApp("x")
    await watch(app, "9")
    await unwatch(app, "9")
    assert app.calls == [("follow", "9"), ("notify_on", "9"), ("notify_off", "9"), ("unfollow", "9")]


async def test_corrupt_session_file_is_removed_and_login_continues(tmp_path):
    import json
    bad = tmp_path / "a.tw_session"
    bad.write_text("{trunc", encoding="utf-8")

    def factory(path):
        if bad.exists():
            raise json.JSONDecodeError("bad", "{trunc", 1)
        return FakeApp(path)

    pool = ClientPool((("a", "T"),), tmp_path, factory=factory, retry_delay=0)
    await pool.login_all()
    assert not bad.exists()
    assert pool.ok_names() == ["a"]


async def test_factory_failure_marks_failed_and_others_continue(tmp_path):
    def factory(path):
        if Path(path).name == "a":
            raise OSError("disk")
        return FakeApp(path)

    pool = ClientPool((("a", "T"), ("b", "T")), tmp_path, factory=factory, retry_delay=0)
    await pool.login_all()
    assert pool.ok_names() == ["b"]
    assert pool.states["a"].error
