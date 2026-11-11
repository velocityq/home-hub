"""The guards added in the public prep (11 Nov 2026): DNS rebinding, JSON only posts, security headers,
and what the static route will not serve."""
from hubserver.app import allowed_hosts, host_ok

from .conftest import auth, build, close


def test_host_ok_rules():
    names = allowed_hosts({"allowed_hosts": ["hub.home.example", "  example.local. "]})
    for good in ("127.0.0.1:8790", "192.0.2.10:8790", "[::1]:8790", "localhost:8790", "LOCALHOST",
                 "hub.home.example:8790", "example.local", "192.0.2.10"):
        assert host_ok(good, names), good
    for bad in ("evil.example:8790", "evil.example", "", "127.0.0.1.evil.example:8790", "localhost.evil.example",
                "hub.home.example.evil.example"):
        assert not host_ok(bad, names), bad


async def test_rebinding_host_is_refused(hub):
    """A page on evil.example that points its own name at the hub sends Host: evil.example."""
    for path in ("/api/health", "/", "/api/state", "/spotify/login"):
        r = await hub.client.get(path, headers={"Host": "evil.example:8790", **auth()}, allow_redirects=False)
        assert r.status == 421, path
        assert r.headers["X-Frame-Options"] == "DENY"
    r = await hub.client.get("/api/health", headers={"Host": "127.0.0.1:8790"})
    assert r.status == 200


async def test_posts_must_be_json(hub):
    c = hub.client
    for ctype in ("text/plain", "application/x-www-form-urlencoded", "multipart/form-data; boundary=x"):
        r = await c.post("/api/action", data='{"action": "aircon.power", "args": {"on": false}}',
                         headers={**auth(), "Content-Type": ctype})
        assert r.status == 415, ctype
    r = await c.post("/api/pair", data="code=123456", headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status == 415
    r = await c.post("/api/action", json={"action": "aircon.set_temp", "args": {"value": 22}}, headers=auth())
    assert r.status == 200


async def test_security_headers_everywhere(hub):
    for path, extra in (("/api/health", {}), ("/api/state", auth()), ("/api/nothing", auth()), ("/nope.js", {})):
        r = await hub.client.get(path, headers=extra)
        assert r.headers["X-Content-Type-Options"] == "nosniff", path
        assert r.headers["Referrer-Policy"] == "no-referrer", path
        assert r.headers["X-Frame-Options"] == "DENY", path
        assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"], path


async def test_static_route_hides_dot_files_and_tests(home):
    wall = home / "wall"
    (wall / "tests" / "shots").mkdir(parents=True)
    (wall / "index.html").write_text("<h1>wall</h1>")
    (wall / "app.js").write_text("1")
    (wall / ".env").write_text("SECRET=1")
    (wall / "tests" / "shots" / "a.png").write_text("png")
    c = await build(home, wall_dir=str(wall))
    try:
        assert (await c.client.get("/app.js")).status == 200
        for path in ("/.env", "/wall/.env", "/tests/shots/a.png", "/wall/tests/shots/a.png", "/%2eenv"):
            r = await c.client.get(path)
            assert r.status == 404, path
    finally:
        await close(c)
