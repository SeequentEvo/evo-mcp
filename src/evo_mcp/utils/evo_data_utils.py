# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Utility functions for data and object operations.
"""

from evo.common import APIConnector
from evo.common.io import ChunkedIOManager, HTTPSource, StorageDestination
from evo.objects import ObjectAPIClient


def extract_data_references(object_dict: dict) -> list[str]:
    """Extract all data blob references from an object definition."""
    data_values = []
    
    def recurse(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key == 'data' and isinstance(value, str):
                    data_values.append(value)
                else:
                    recurse(value)
        elif isinstance(obj, list):
            for item in obj:
                recurse(item)
    
    recurse(object_dict)
    return data_values


async def copy_object_data(
    source_client: ObjectAPIClient,
    target_client: ObjectAPIClient,
    downloaded_object,
    data_identifiers: list[str],
    connector: APIConnector
) -> None:
    """Copy data blobs from source to target workspace."""
    if not data_identifiers:
        return
    
    for download_ctx in downloaded_object.prepare_data_download(data_identifiers):
        upload_ctx, = [s async for s in target_client.prepare_data_upload([download_ctx.name])]
        
        async with (
            HTTPSource(download_ctx.get_download_url, connector.transport) as src,
            StorageDestination(upload_ctx.get_upload_url, connector.transport) as dst
        ):
            await ChunkedIOManager().run(src, dst)
            await dst.commit()
