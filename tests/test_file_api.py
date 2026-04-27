"""Tests de seguridad y funcionalidad para los endpoints de archivos.

Cubre:
  - path-traversal (T1): rutas fuera del workspace → 403
  - _resolve_safe fuera del home → 403
  - _sanitize_filename (T2): nombres peligrosos quedan limpios
  - CRUD básico: crear, leer contenido, renombrar, duplicar, borrar (T5)
  - search y grep devuelven resultados esperados (T5)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from web.api import router, _sanitize_filename, _resolve_safe
from fastapi import HTTPException


# --------------------------------------------------------------------------
# App fixture
# --------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app, raise_server_exceptions=False)


# --------------------------------------------------------------------------
# _sanitize_filename unit tests (T2)
# --------------------------------------------------------------------------

class TestSanitizeFilename:
    def test_strips_directory_component(self):
        assert _sanitize_filename("../../etc/passwd") == "passwd"

    def test_removes_null_bytes(self):
        assert "\x00" not in _sanitize_filename("file\x00.txt")

    def test_leading_dots_stripped(self):
        name = _sanitize_filename(".hidden")
        assert not name.startswith(".")

    def test_leading_spaces_stripped(self):
        name = _sanitize_filename("  spaces.txt")
        assert not name.startswith(" ")

    def test_empty_becomes_upload(self):
        assert _sanitize_filename("") == "upload"

    def test_normal_name_unchanged(self):
        assert _sanitize_filename("my_file.py") == "my_file.py"


# --------------------------------------------------------------------------
# _resolve_safe unit tests (T1)
# --------------------------------------------------------------------------

class TestResolveSafe:
    def test_rejects_path_outside_workspace(self, tmp_path):
        workspace = str(tmp_path / "workspace")
        Path(workspace).mkdir()
        with pytest.raises(HTTPException) as exc:
            _resolve_safe("/etc/passwd", workspace)
        assert exc.value.status_code == 403

    def test_accepts_path_inside_workspace(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        target = workspace / "subdir" / "file.txt"
        result = _resolve_safe(str(target), str(workspace))
        assert result == target.resolve()

    def test_rejects_symlink_escape(self, tmp_path):
        workspace = tmp_path / "workspace"
        workspace.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret")
        link = workspace / "link.txt"
        link.symlink_to(outside)
        # resolve() follows symlinks, so the resolved path points outside workspace
        with pytest.raises(HTTPException) as exc:
            _resolve_safe(str(link), str(workspace))
        assert exc.value.status_code == 403

    def test_rejects_etc_without_workspace(self):
        with pytest.raises(HTTPException) as exc:
            _resolve_safe("/etc/passwd")
        assert exc.value.status_code == 403

    def test_accepts_home_subpath_without_workspace(self, tmp_path):
        # tmp_path is usually under /tmp, NOT under home — we use home directly
        home = Path.home()
        result = _resolve_safe(str(home))
        assert result == home.resolve()


# --------------------------------------------------------------------------
# HTTP endpoint tests (integration over TestClient)
# --------------------------------------------------------------------------

@pytest.fixture()
def ws(tmp_path):
    """A temporary workspace with a few files."""
    (tmp_path / "hello.txt").write_text("hello world\nline 2\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "nested.py").write_text("x = 1\n")
    return tmp_path


class TestListFiles:
    def test_lists_workspace(self, client, ws):
        r = client.get("/api/files", params={"path": str(ws), "workspace": str(ws)})
        assert r.status_code == 200
        names = {i["name"] for i in r.json()["items"]}
        assert "hello.txt" in names
        assert "sub" in names

    def test_path_traversal_rejected(self, client, ws):
        r = client.get("/api/files", params={"path": "/etc", "workspace": str(ws)})
        assert r.status_code == 403


class TestFileContent:
    def test_reads_file(self, client, ws):
        r = client.get("/api/file-content", params={
            "path": str(ws / "hello.txt"),
            "workspace": str(ws),
        })
        assert r.status_code == 200
        assert "hello world" in r.json()["content"]

    def test_path_traversal_rejected(self, client, ws):
        r = client.get("/api/file-content", params={
            "path": "/etc/passwd",
            "workspace": str(ws),
        })
        assert r.status_code == 403


class TestFileCRUD:
    def test_create_and_delete_file(self, client, ws):
        new_path = str(ws / "new_file.txt")
        # create
        r = client.post("/api/files/create", json={
            "path": new_path,
            "workspace": str(ws),
        })
        assert r.status_code == 200
        assert Path(new_path).exists()

        # permanent delete (trash=false so it doesn't depend on home-jail for .trash/)
        r = client.delete("/api/files/delete", params={"path": new_path, "workspace": str(ws), "trash": "false"})
        assert r.status_code == 200
        assert not Path(new_path).exists()

    def test_delete_moves_to_trash(self, client, ws):
        path = str(ws / "hello.txt")
        r = client.delete("/api/files/delete", params={"path": path, "workspace": str(ws), "trash": "true"})
        assert r.status_code == 200
        data = r.json()
        assert data["trashed"] is True
        assert not Path(path).exists()
        assert Path(data["trash_path"]).exists()

    def test_create_outside_workspace_rejected(self, client, ws, tmp_path):
        other = tmp_path.parent / "evil.txt"
        r = client.post("/api/files/create", json={
            "path": str(other),
            "workspace": str(ws),
        })
        assert r.status_code == 403

    def test_mkdir(self, client, ws):
        new_dir = str(ws / "new_dir")
        r = client.post("/api/files/mkdir", json={"path": new_dir, "workspace": str(ws)})
        assert r.status_code == 200
        assert Path(new_dir).is_dir()

    def test_rename(self, client, ws):
        r = client.post("/api/files/rename", json={
            "path": str(ws / "hello.txt"),
            "new_name": "renamed.txt",
            "workspace": str(ws),
        })
        assert r.status_code == 200
        assert (ws / "renamed.txt").exists()
        assert not (ws / "hello.txt").exists()

    def test_duplicate(self, client, ws):
        r = client.post("/api/files/duplicate", json={
            "path": str(ws / "hello.txt"),
            "workspace": str(ws),
        })
        assert r.status_code == 200
        assert (ws / "hello_copia.txt").exists()

    def test_move(self, client, ws):
        r = client.post("/api/files/move", json={
            "src_path": str(ws / "hello.txt"),
            "dst_dir": str(ws / "sub"),
            "workspace": str(ws),
        })
        assert r.status_code == 200
        assert (ws / "sub" / "hello.txt").exists()
        assert not (ws / "hello.txt").exists()

    def test_delete_outside_workspace_rejected(self, client, ws):
        r = client.delete("/api/files/delete", params={
            "path": "/etc/hosts",
            "workspace": str(ws),
        })
        assert r.status_code == 403


class TestSearchFiles:
    def test_finds_file_by_name(self, client, ws):
        r = client.get("/api/files/search", params={
            "path": str(ws),
            "q": "hello",
            "workspace": str(ws),
        })
        assert r.status_code == 200
        names = [i["name"] for i in r.json()["items"]]
        assert "hello.txt" in names

    def test_path_traversal_rejected(self, client, ws):
        r = client.get("/api/files/search", params={
            "path": "/etc",
            "q": "passwd",
            "workspace": str(ws),
        })
        assert r.status_code == 403


class TestGrepFiles:
    def test_finds_content(self, client, ws):
        r = client.get("/api/files/grep", params={
            "path": str(ws),
            "q": "hello",
            "workspace": str(ws),
        })
        assert r.status_code == 200
        groups = r.json()["groups"]
        assert any(g["file_name"] == "hello.txt" for g in groups)

    def test_path_traversal_rejected(self, client, ws):
        r = client.get("/api/files/grep", params={
            "path": "/etc",
            "q": "root",
            "workspace": str(ws),
        })
        assert r.status_code == 403
