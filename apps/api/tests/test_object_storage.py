from pathlib import Path

from fastapi.testclient import TestClient

from app.providers.object_storage import LocalObjectStorageProvider, content_checksum, knowledge_object_key
from tests.conftest import login


def test_local_object_storage_round_trip(tmp_path: Path) -> None:
    store = LocalObjectStorageProvider(root=str(tmp_path))
    key = "tenant/demo/knowledge/doc/v1/source"
    store.put(key, b"hello-bytes", content_type="text/plain")
    assert store.exists(key)
    assert store.get(key) == b"hello-bytes"
    assert content_checksum(b"hello-bytes") == content_checksum(store.get(key))
    assert "knowledge" in store.presign(key)


def test_knowledge_object_key_is_tenant_scoped() -> None:
    from uuid import uuid4

    tenant = uuid4()
    doc = uuid4()
    key = knowledge_object_key(tenant_id=tenant, document_id=doc)
    assert str(tenant) in key
    assert str(doc) in key
    assert key.endswith("/source")


def test_knowledge_upload_stores_bytes_and_downloads(client: TestClient, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OBJECT_STORAGE_LOCAL_ROOT", str(tmp_path))
    from app.core.config import get_settings

    get_settings.cache_clear()
    headers = login(client)
    uploaded = client.post(
        "/api/v1/ai/knowledge",
        headers=headers,
        data={"title": "Storage note"},
        files={"file": ("note.txt", b"revenue operating system", "text/plain")},
    )
    assert uploaded.status_code == 200, uploaded.text
    source_id = uploaded.json()["data"]["id"]
    downloaded = client.get(f"/api/v1/ai/knowledge/{source_id}/file", headers=headers)
    assert downloaded.status_code == 200
    assert downloaded.content == b"revenue operating system"
    hits = client.get("/api/v1/ai/knowledge/search", headers=headers, params={"q": "operating"}).json()["data"]
    assert any("operating" in row["text"] for row in hits)
    get_settings.cache_clear()
