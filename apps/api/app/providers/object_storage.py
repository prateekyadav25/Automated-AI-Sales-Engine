"""Object storage. Domain services depend on this protocol, not SDK clients."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Protocol
from urllib.parse import quote
from uuid import UUID

import httpx

from app.core.config import get_settings


class ObjectStorageProvider(Protocol):
    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str: ...
    def get(self, key: str) -> bytes: ...
    def exists(self, key: str) -> bool: ...
    def presign(self, key: str, *, expires_seconds: int = 300) -> str: ...


class LocalObjectStorageProvider:
    def __init__(self, root: str | None = None) -> None:
        settings = get_settings()
        self.root = Path(root or settings.object_storage_local_root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        _ = content_type
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def exists(self, key: str) -> bool:
        return (self.root / key).exists()

    def presign(self, key: str, *, expires_seconds: int = 300) -> str:
        _ = expires_seconds
        return f"/api/v1/ai/knowledge/files/{quote(key, safe='')}"


class S3CompatibleObjectStorageProvider:
    """Path-style S3/MinIO via boto3 when configured, otherwise HTTP PUT to the endpoint."""

    def __init__(self) -> None:
        settings = get_settings()
        self.endpoint = settings.s3_endpoint.rstrip("/")
        self.bucket = settings.s3_bucket
        self.access_key = settings.s3_access_key
        self.secret_key = settings.s3_secret_key

    def _client(self):
        import boto3
        from botocore.client import Config

        return boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            config=Config(signature_version="s3v4"),
            region_name="us-east-1",
        )

    def put(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> str:
        try:
            self._client().put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
            return key
        except Exception:
            httpx.put(f"{self.endpoint}/{self.bucket}/{key}", content=data, timeout=15.0).raise_for_status()
            return key

    def get(self, key: str) -> bytes:
        try:
            return self._client().get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception:
            response = httpx.get(f"{self.endpoint}/{self.bucket}/{key}", timeout=15.0)
            response.raise_for_status()
            return response.content

    def exists(self, key: str) -> bool:
        try:
            self._client().head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def presign(self, key: str, *, expires_seconds: int = 300) -> str:
        try:
            return self._client().generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=expires_seconds,
            )
        except Exception:
            return f"/api/v1/ai/knowledge/files/{quote(key, safe='')}"


class MinioObjectStorageProvider(S3CompatibleObjectStorageProvider):
    pass


class S3ObjectStorageProvider(S3CompatibleObjectStorageProvider):
    pass


def knowledge_object_key(*, tenant_id: UUID, document_id: UUID, version: str = "v1") -> str:
    return f"tenant/{tenant_id}/knowledge/{document_id}/{version}/source"


def model_artifact_key(*, tenant_id: UUID, task_key: str, version: str) -> str:
    return f"tenant/{tenant_id}/models/{task_key}/{version}/artifact"


def dataset_object_key(*, tenant_id: UUID, task_key: str, version: str) -> str:
    return f"tenant/{tenant_id}/models/{task_key}/{version}/dataset.jsonl"


def get_object_storage() -> ObjectStorageProvider:
    settings = get_settings()
    backend = (settings.object_storage_provider or "local").lower()
    if backend in {"minio", "s3"} and settings.s3_endpoint:
        if backend == "minio":
            return MinioObjectStorageProvider()
        return S3ObjectStorageProvider()
    return LocalObjectStorageProvider()


def content_checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
