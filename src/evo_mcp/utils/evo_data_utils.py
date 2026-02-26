"""
Utility functions for data and object operations.
"""

from uuid import UUID

from evo.common import APIConnector
from evo.common.io import ChunkedIOManager, HTTPSource, StorageDestination
from evo.objects import ObjectAPIClient

from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.utils.data_analysis_utils import (
    get_downhole_collection,
    get_collection_info,
    get_object_type,
)


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


async def discover_objects(
    workspace_id: str,
    object_types: list[str] | None = None,
    deleted: bool = False,
    limit: int = 100,
) -> list[dict]:
    """List all objects in a workspace, optionally filtered by object type.

    Args:
        workspace_id: Workspace UUID string.
        object_types: Optional list of schema sub-classifications to include
            (e.g., ['downhole-collection', 'downhole-intervals']). If None, all types returned.
        deleted: Include deleted objects.
        limit: Maximum number of results.

    Returns:
        List of object metadata dicts with id, name, path, schema_id, version_id, created_at.
    """
    await ensure_initialized()
    object_client = await evo_context.get_object_client(UUID(workspace_id))

    service_health = await object_client.get_service_health()
    service_health.raise_for_status()

    objects = await object_client.list_objects(
        schema_id=None,
        deleted=deleted,
        limit=limit,
    )

    result = [
        {
            "id": str(obj.id),
            "name": obj.name,
            "path": obj.path,
            "schema_id": obj.schema_id.sub_classification,
            "version_id": obj.version_id,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
        }
        for obj in objects.items()
    ]

    if object_types:
        result = [o for o in result if o["schema_id"] in object_types]

    return result


async def load_downhole_object(workspace_id: str, object_id: str, version: str = "") -> tuple[object, dict, str, str, list[dict]]:
    """Download an Evo downhole object and inspect its collections.

    Args:
        workspace_id: Workspace UUID string.
        object_id: Object UUID string.
        version: Optional version ID (empty string for latest).

    Returns:
        Tuple of (obj, obj_dict, object_name, object_type, collections_info).
    """
    obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)

    object_name = obj_dict.get('name', 'Unknown')
    object_type_str = get_object_type(obj_dict)
    collections_info = get_collection_info(obj_dict)

    return obj, obj_dict, object_name, object_type_str, collections_info
