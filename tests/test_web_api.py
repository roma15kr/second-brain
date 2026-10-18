from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kb.api.app import build_app


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<div id=root></div>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def test_spa_fallback_serves_index(dist):
    client = TestClient(build_app(dist))
    r = client.get("/briefs/12")
    assert r.status_code == 200 and "<div id=root>" in r.text
    assert r.headers["cache-control"] == "no-cache"
    assert client.get("/").text == r.text
    assert client.get("/assets/app.js").text == "console.log(1)"


def test_api_paths_never_fall_back_to_spa(dist):
    client = TestClient(build_app(dist))
    assert client.get("/api/health").json() == {"ok": True}
    r = client.get("/api/nope")  # no session: refused before routing, never the SPA
    assert r.status_code == 401 and "root" not in r.text


def test_path_traversal_serves_index_not_file(dist, tmp_path_factory):
    secret = dist.parent / "secret.txt"
    secret.write_text("nope")
    r = TestClient(build_app(dist)).get("/..%2Fsecret.txt")
    assert "nope" not in r.text


def test_missing_build_is_explicit():
    assert TestClient(build_app(None)).get("/").status_code == 503


def test_kb_web_entry_point_serves_built_spa(dist, monkeypatch):
    from kb import cli

    monkeypatch.setenv("KB_WEB_DIST", str(dist))
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    args = cli.build_parser().parse_args(["web"])
    assert args.func is cli.cmd_web and args.port == 8001
    assert "<div id=root>" in TestClient(cli.build_web_app()).get("/today").text


def test_pwa_files_served_with_right_headers(dist):
    (dist / "sw.js").write_text("self.addEventListener('push', () => {})")
    (dist / "manifest.webmanifest").write_text('{"name": "Second brain"}')
    client = TestClient(build_app(dist))
    assert client.get("/sw.js").headers["cache-control"] == "no-cache"
    r = client.get("/manifest.webmanifest")
    assert r.headers["content-type"].startswith("application/manifest+json")
