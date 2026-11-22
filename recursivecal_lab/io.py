"""Small, strict file contracts shared by the CLI and local API."""
from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path
import tempfile
import zlib
from typing import Any

MAX_INPUT_BYTES = 8 * 1024 * 1024
MAX_REPORT_BYTES = 128 * 1024 * 1024


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def loads(text: str) -> Any:
    return json.loads(text, parse_constant=_reject_constant, object_pairs_hook=_unique_object)


def read_json(path: str | Path, *, max_bytes: int = MAX_INPUT_BYTES) -> Any:
    path = Path(path)
    if path.stat().st_size > max_bytes:
        raise ValueError(f"JSON input exceeds {max_bytes // (1024 * 1024)} MiB")
    try:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rb") as handle:
            raw = handle.read(max_bytes + 1)
    except (gzip.BadGzipFile, EOFError, zlib.error) as exc:
        raise ValueError("invalid or truncated gzip JSON input") from exc
    if len(raw) > max_bytes:
        raise ValueError(f"decompressed JSON input exceeds {max_bytes} bytes")
    return loads(raw.decode("utf-8"))


def write_json(path: str | Path, value: Any, *, overwrite: bool = False) -> Path:
    """Write a complete JSON artifact atomically, never half a result."""
    path = Path(path)
    encoded = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if path.suffix == ".gz":
        buffer = io.BytesIO()
        with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0) as handle:
            handle.write(encoded)
        encoded = buffer.getvalue()
    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} exists; choose another output or pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".recursivecal-", delete=False) as handle:
            temporary = handle.name
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            os.link(temporary, path)
            os.unlink(temporary)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return path.resolve()

