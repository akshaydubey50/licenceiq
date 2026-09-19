"""Verify the private MinIO object-store boundary without live infrastructure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import BinaryIO
from uuid import UUID

import pytest

from app.repositories.object_store import (
    ListedObject,
    MinioObjectStore,
    ObjectResponse,
    ObjectStoreError,
)


class FakeResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content
        self.closed = False
        self.released = False

    def read(self) -> bytes:
        return self._content

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


@dataclass
class FakeListedObject:
    object_name: str | None


class FakeMinioClient:
    """In-memory structural double for the subset of the MinIO SDK in use."""

    def __init__(self, *, bucket_exists: bool = False) -> None:
        self.bucket_present = bucket_exists
        self.objects: dict[tuple[str, str], bytes] = {}
        self.content_types: dict[tuple[str, str], str] = {}
        self.made_buckets: list[str] = []
        self.list_requests: list[tuple[str, str | None, bool]] = []
        self.last_response: FakeResponse | None = None
        self.failure: Exception | None = None

    def bucket_exists(self, bucket_name: str) -> bool:
        self._maybe_fail()
        return self.bucket_present

    def make_bucket(self, bucket_name: str) -> object:
        self._maybe_fail()
        self.bucket_present = True
        self.made_buckets.append(bucket_name)
        return object()

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> object:
        self._maybe_fail()
        content = data.read(length)
        self.objects[(bucket_name, object_name)] = content
        self.content_types[(bucket_name, object_name)] = content_type
        return object()

    def get_object(self, bucket_name: str, object_name: str) -> ObjectResponse:
        self._maybe_fail()
        response = FakeResponse(self.objects[(bucket_name, object_name)])
        self.last_response = response
        return response

    def remove_object(self, bucket_name: str, object_name: str) -> object:
        self._maybe_fail()
        self.objects.pop((bucket_name, object_name), None)
        return object()

    def list_objects(
        self,
        bucket_name: str,
        prefix: str | None = None,
        recursive: bool = False,
    ) -> Iterable[ListedObject]:
        self._maybe_fail()
        self.list_requests.append((bucket_name, prefix, recursive))
        return [
            FakeListedObject(name)
            for stored_bucket, name in self.objects
            if stored_bucket == bucket_name and (prefix is None or name.startswith(prefix))
        ]

    def _maybe_fail(self) -> None:
        if self.failure is not None:
            raise self.failure


def make_store(client: FakeMinioClient) -> MinioObjectStore:
    return MinioObjectStore(client, bucket="licenceiq-private", prefix="documents/content")


def test_initialize_creates_only_a_missing_bucket() -> None:
    missing_client = FakeMinioClient()
    existing_client = FakeMinioClient(bucket_exists=True)

    make_store(missing_client).initialize()
    make_store(existing_client).initialize()

    assert missing_client.made_buckets == ["licenceiq-private"]
    assert existing_client.made_buckets == []


@pytest.mark.parametrize(
    "prefix",
    ["", "/documents", "documents/", "documents//content", "documents/../content", "UPPER"],
)
def test_prefix_must_be_a_bounded_safe_internal_path(prefix: str) -> None:
    with pytest.raises(ValueError, match="prefix"):
        MinioObjectStore(FakeMinioClient(), bucket="licenceiq-private", prefix=prefix)


@pytest.mark.parametrize(
    "key",
    ["licence.png", "../private", "token-secret", "f47ac10b-58cc-11cf-a447-001122334455"],
)
def test_only_canonical_generated_uuid4_keys_are_accepted(key: str) -> None:
    with pytest.raises(ValueError, match="UUID4"):
        make_store(FakeMinioClient()).put(key, b"private", content_type="image/png")


def test_content_round_trip_uses_a_generated_private_key() -> None:
    client = FakeMinioClient(bucket_exists=True)
    store = make_store(client)
    key = store.generate_key()

    store.put(key, b"licence bytes", content_type="image/png")

    assert UUID(key).version == 4
    assert store.get(key) == b"licence bytes"
    assert client.objects == {
        ("licenceiq-private", f"documents/content/{key}.bin"): b"licence bytes"
    }
    assert client.last_response is not None
    assert client.last_response.closed is True
    assert client.last_response.released is True


def test_delete_is_idempotent() -> None:
    client = FakeMinioClient(bucket_exists=True)
    store = make_store(client)
    key = store.generate_key()
    store.put(key, b"content", content_type="application/octet-stream")

    store.delete(key)
    store.delete(key)

    assert client.objects == {}


def test_list_is_limited_to_the_configured_prefix_and_valid_keys() -> None:
    client = FakeMinioClient(bucket_exists=True)
    store = make_store(client)
    first = store.generate_key()
    second = store.generate_key()
    for key in (first, second):
        store.put(key, key.encode(), content_type="application/octet-stream")
    client.objects[("licenceiq-private", "other/foreign.bin")] = b"foreign"
    client.objects[("licenceiq-private", "documents/content/not-a-key.bin")] = b"invalid"
    client.objects[("another-bucket", f"documents/content/{store.generate_key()}.bin")] = b"other"

    assert store.list_keys() == tuple(sorted((first, second)))
    assert client.list_requests == [("licenceiq-private", "documents/content/", True)]


def test_provider_write_failure_is_normalized_and_redacted() -> None:
    private_filename = "Akshay-driving-licence.png"
    private_token = "bearer-private-token"
    client = FakeMinioClient(bucket_exists=True)
    client.failure = RuntimeError(f"provider rejected {private_filename} using {private_token}")
    store = make_store(client)
    key = store.generate_key()

    with pytest.raises(ObjectStoreError) as captured:
        store.put(key, b"private document bytes", content_type="image/png")

    rendered = repr(captured.value)
    assert captured.value.operation == "write"
    assert str(captured.value) == "Object storage write failed."
    assert key not in rendered
    assert private_filename not in rendered
    assert private_token not in rendered
    assert "private document bytes" not in rendered


def test_generated_object_names_never_contain_filename_or_token() -> None:
    client = FakeMinioClient(bucket_exists=True)
    store = make_store(client)
    key = store.generate_key()
    filename = "friendly-licence.png"
    token = "secret-auth-token"

    store.put(key, f"{filename}:{token}".encode(), content_type="image/png")

    object_names = [object_name for _, object_name in client.objects]
    assert object_names == [f"documents/content/{key}.bin"]
    assert filename not in object_names[0]
    assert token not in object_names[0]
