# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Helpers for working with Evo SDK downloaded objects."""

from __future__ import annotations

from typing import Any


def downloaded_object_data_links(downloaded: Any) -> list[dict[str, Any]]:
    """Return stable data-link metadata from a downloaded Evo object.

    The Evo SDK exposes downloaded-object data URLs through a urls-by-name mapping.
    This helper normalizes that into a consistent list of link dictionaries used by
    multiple MCP tools.
    """
    urls_by_name = getattr(downloaded, "urls_by_name", None)
    if urls_by_name is None:
        urls_by_name = getattr(downloaded, "_urls_by_name", None)

    if not urls_by_name:
        return []

    filtered = sorted(
        ((name, url) for name, url in urls_by_name.items() if name and url),
        key=lambda item: str(item[0]),
    )

    return [
        {
            "index": index,
            "name": str(name),
            "id": str(name),
            "download_url": str(download_url),
        }
        for index, (name, download_url) in enumerate(filtered, start=1)
    ]
