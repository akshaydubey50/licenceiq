"""Private generated-key object storage for S3-compatible providers."""

from __future__ import annotations

import re
from collections.abc import Iterable
from io import BytesIO
from typing import BinaryIO, Literal, Protocol
from uuid import UUID, uuid4

ObjectStoreOperation = Literal["initialize", "write", "read", "delete", "list"]

_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PREFIX_PART_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


class ObjectStoreError(RuntimeError):
    """Expose a stable operation failure without provider or private details."""

    def __init__(self, operation: ObjectStoreOperation) -> None:
        self.operation = operation
        super().__init__(f"Object storage {operation} failed.")


class ObjectResponse(Protocol):
    """Readable response returned by the standard MinIO Python client."""

    def read(self) -> bytes: ...

    def close(self) -> None: ...

    def release_conn(self) -> None: ...


class ListedObject(Protocol):
    """Small portion of a MinIO list result used by the adapter."""

    object_name: str | None


class MinioClient(Protocol):
    """Structural type matching the MinIO client calls used by this module."""

    def bucket_exists(self, bucket_name: str) -> bool: ...

    def make_bucket(self, bucket_name: str) -> object: ...

    def put_object(
        self,
        bucket_name: str,
        object_name: str,
        data: BinaryIO,
        length: int,
        content_type: str,
    ) -> object: ...

    def get_object(self, bucket_name: str, object_name: str) -> ObjectResponse: ...

    def remove_object(self, bucket_name: str, object_name: str) -> object: ...

    def list_objects(
        self,
        bucket_name: str,
        prefix: str | None = None,
        recursive: bool = False,
    ) -> Iterable[ListedObject]: ...


class PrivateObjectStore(Protocol):
    """Storage behavior required by a later document repository adapter."""

    def initialize(self) -> None: ...

    def generate_key(self) -> str: ...

    def put(self, key: str, content: bytes, *, content_type: str) -> None: ...

    def get(self, key: str) -> bytes: ...

    def delete(self, key: str) -> None: ...

    def list_keys(self) -> tuple[str, ...]: ...


class MinioObjectStore:
    """Store private objects in one bucket beneath a fixed internal prefix.

    The public storage key is a generated UUID only. Provider-facing object names
    are derived from that UUID, so caller filenames, tokens, and document content
    never participate in object naming.
    """

    def __init__(self, client: MinioClient, *, bucket: str, prefix: str) -> None:
        self._validate_bucket(bucket)
        self._validate_prefix(prefix)
        self._client = client
        self._bucket = bucket
        self._prefix = prefix

    def initialize(self) -> None:
        """Create the private bucket when it does not already exist."""
        try:
            if not self._client.bucket_exists(self._bucket):
                self._client.make_bucket(self._bucket)
        except Exception:
            raise ObjectStoreError("initialize") from None

    def generate_key(self) -> str:
        """Return a filename- and token-independent key for a new object."""
        return str(uuid4())

    def put(self, key: str, content: bytes, *, content_type: str) -> None:
        """Publish bytes at an already generated private key."""
        object_name = self._object_name(key)
        self._validate_content_type(content_type)
        try:
            self._client.put_object(
                self._bucket,
                object_name,
                BytesIO(content),
                len(content),
                content_type,
            )
        except Exception:
            raise ObjectStoreError("write") from None

    def get(self, key: str) -> bytes:
        """Read all bytes for one validated private key."""
        object_name = self._object_name(key)
        response: ObjectResponse | None = None
        try:
            response = self._client.get_object(self._bucket, object_name)
            return response.read()
        except Exception:
            raise ObjectStoreError("read") from None
        finally:
            if response is not None:
                self._release_response(response)

    def delete(self, key: str) -> None:
        """Delete one validated object; MinIO deletion is idempotent."""
        object_name = self._object_name(key)
        try:
            self._client.remove_object(self._bucket, object_name)
        except Exception:
            raise ObjectStoreError("delete") from None

    def list_keys(self) -> tuple[str, ...]:
        """List valid keys only from this adapter's bounded prefix."""
        bounded_prefix = f"{self._prefix}/"
        try:
            keys = []
            for item in self._client.list_objects(
                self._bucket,
                prefix=bounded_prefix,
                recursive=True,
            ):
                object_name = item.object_name
                if object_name is None or not object_name.startswith(bounded_prefix):
                    continue
                suffix = object_name.removeprefix(bounded_prefix)
                if not suffix.endswith(".bin") or "/" in suffix:
                    continue
                key = suffix.removesuffix(".bin")
                try:
                    self._validate_key(key)
                except ValueError:
                    continue
                keys.append(key)
            return tuple(sorted(keys))
        except Exception:
            raise ObjectStoreError("list") from None

    def _object_name(self, key: str) -> str:
        self._validate_key(key)
        return f"{self._prefix}/{key}.bin"

    @staticmethod
    def _validate_key(key: str) -> None:
        try:
            parsed = UUID(key)
        except (AttributeError, TypeError, ValueError):
            raise ValueError("Object key must be a canonical generated UUID4.") from None
        if parsed.version != 4 or str(parsed) != key:
            raise ValueError("Object key must be a canonical generated UUID4.")

    @staticmethod
    def _validate_bucket(bucket: str) -> None:
        if not _BUCKET_PATTERN.fullmatch(bucket) or ".." in bucket:
            raise ValueError("Bucket must be a valid private S3 bucket name.")

    @staticmethod
    def _validate_prefix(prefix: str) -> None:
        parts = prefix.split("/")
        if (
            not prefix
            or len(prefix) > 128
            or any(not _PREFIX_PART_PATTERN.fullmatch(part) for part in parts)
        ):
            raise ValueError("Object prefix must contain safe lowercase path segments.")

    @staticmethod
    def _validate_content_type(content_type: str) -> None:
        if (
            not content_type
            or len(content_type) > 127
            or "\r" in content_type
            or "\n" in content_type
        ):
            raise ValueError("Content type must be a valid media type value.")

    @staticmethod
    def _release_response(response: ObjectResponse) -> None:
        try:
            response.close()
        except Exception:
            pass
        try:
            response.release_conn()
        except Exception:
            pass
