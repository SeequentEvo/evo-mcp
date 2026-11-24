# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Manually check stateless MCP against a client-delegated HTTP server."""

import argparse
import asyncio

from fastmcp import Client
from fastmcp.client.auth import OAuth

STATELESS_PROTOCOL = "2026-07-28"


async def check_stateless(url: str) -> None:
    async with Client(url, auth=OAuth(), mode="auto") as client:
        if client.protocol_version != STATELESS_PROTOCOL:
            raise RuntimeError(f"Expected stateless protocol {STATELESS_PROTOCOL}, got {client.protocol_version}")

        created = await client.call_tool("create_session")
        session_id = created.data
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("create_session did not return a session ID")
        try:
            result = await client.call_tool("list_my_instances", {"session_id": session_id})
            if not isinstance(result.data, list):
                raise RuntimeError(
                    f"list_my_instances returned an unexpected result type: {type(result.data).__name__}"
                )
        finally:
            await client.call_tool("end_session", {"session_id": session_id})

        print(f"PASS stateless: {client.protocol_version}, authenticated conversation and list_my_instances")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5000/mcp", help="MCP endpoint URL")
    args = parser.parse_args()
    asyncio.run(check_stateless(args.url))


if __name__ == "__main__":
    main()
