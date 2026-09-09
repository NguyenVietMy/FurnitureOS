from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.main import create_app


@pytest.fixture
def static_client(tmp_path: Path) -> TestClient:
    (tmp_path / "dist" / "assets").mkdir(parents=True)
    (tmp_path / "public" / "products").mkdir(parents=True)
    (tmp_path / "public" / "decoders").mkdir(parents=True)
    (tmp_path / "public" / "images").mkdir(parents=True)
    (tmp_path / "public" / "images" / "room.jpg").write_bytes(b"photo")
    (tmp_path / "public" / "icon.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
    (tmp_path / "dist" / "index.html").write_text('<script src="/assets/app.js"></script>', encoding="utf-8")
    (tmp_path / "dist" / "assets" / "app.js").write_text("globalThis.booted = true;", encoding="utf-8")
    (tmp_path / "dist" / "assets" / "app.css").write_text("body { color: black; }", encoding="utf-8")
    (tmp_path / "public" / "products" / "mesh.gltf").write_text('{"asset":{"version":"2.0"}}', encoding="utf-8")
    (tmp_path / "public" / "decoders" / "decoder.wasm").write_bytes(b"\x00asm")
    (tmp_path / "secret.txt").write_text("TOP SECRET", encoding="utf-8")
    return TestClient(create_app(tmp_path))


def test_spa_root_serves_html(static_client) -> None:
    response = static_client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_spa_history_fallback_serves_html(static_client) -> None:
    response = static_client.get("/preview/deep-link")
    assert response.status_code == 200
    assert "app.js" in response.text


@pytest.mark.parametrize("asset,media_type", [("app.js", "javascript"), ("app.css", "text/css")])
def test_vite_assets_are_files_with_correct_mime_types(static_client, asset, media_type) -> None:
    response = static_client.get(f"/assets/{asset}")
    assert response.status_code == 200
    assert media_type in response.headers["content-type"]
    assert "<script" not in response.text


def test_public_product_assets_are_served(static_client) -> None:
    response = static_client.get("/products/mesh.gltf")
    assert response.status_code == 200
    assert response.json()["asset"]["version"] == "2.0"


def test_public_decoder_assets_are_served(static_client) -> None:
    response = static_client.get("/decoders/decoder.wasm")
    assert response.status_code == 200
    assert response.content == b"\x00asm"


@pytest.mark.parametrize("path", [
    "/%2e%2e/secret.txt",
    "/..%2Fsecret.txt",
    "/%2e%2e%2fsecret.txt",
    "/%252e%252e%252fsecret.txt",
    "/products/%2e%2e%2f..%2fsecret.txt",
    "/assets/%2e%2e%2f..%2fsecret.txt",
    "/..\\secret.txt",
])
def test_plain_and_encoded_traversal_never_disclose_files(static_client, path) -> None:
    response = static_client.get(path)
    assert response.status_code in {400, 404}
    assert "TOP SECRET" not in response.text


@pytest.mark.parametrize("path", ["/missing.js", "/missing.css", "/favicon.ico", "/pyproject.toml"])
def test_missing_file_requests_do_not_receive_spa_html(static_client, path) -> None:
    response = static_client.get(path)
    assert response.status_code == 404


def test_static_mount_rejects_post(static_client) -> None:
    assert static_client.post("/assets/app.js").status_code == 405


@pytest.mark.parametrize("path", ["/design", "/design/", "/unknown/room"])
def test_app_routes_receive_the_client_router(static_client, path) -> None:
    response = static_client.get(path)
    assert response.status_code == 200
    assert "app.js" in response.text


@pytest.mark.parametrize("path,content_type", [("/images/room.jpg", "image/jpeg"), ("/icon.svg", "image/svg+xml")])
def test_landing_assets_have_correct_content_types(static_client, path, content_type) -> None:
    response = static_client.get(path)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(content_type)


@pytest.mark.parametrize("path", ["/images/missing.jpg", "/images/%2e%2e%2f..%2fsecret.txt", "/api/missing", "/api/missing/deep"])
def test_landing_asset_and_unknown_api_requests_never_fall_back_to_html(static_client, path) -> None:
    response = static_client.get(path)
    assert response.status_code == 404
    assert "TOP SECRET" not in response.text
    assert "app.js" not in response.text
