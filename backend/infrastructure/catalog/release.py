from __future__ import annotations

import json
import re
from collections.abc import Mapping


BUNDLED_CATALOG_RELEASE = "zh-CN.2026-10-17.1"
_RELEASE_PREFIX = "catalog-release:"


def catalog_import_version(
    payload: Mapping[str, object],
    dataset_version: str,
) -> str:
    """Qualify explicit releases for the ledger without changing upstream metadata.

    Legacy versions remain exact, including strings resembling qualified keys.
    The ledger's immutable checksum check still protects completed collisions.
    """
    if "catalog_release" not in payload:
        return dataset_version
    release = payload["catalog_release"]
    if (
        not isinstance(release, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", release) is None
        or dataset_version.startswith(_RELEASE_PREFIX)
    ):
        raise ValueError("CATALOG_RELEASE_INVALID")
    return _RELEASE_PREFIX + json.dumps(
        [dataset_version, release],
        ensure_ascii=False,
        separators=(",", ":"),
    )
