# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Manually check both MCP protocol eras against a client-delegated HTTP server."""

import argparse
import asyncio

from fastmcp import Client
from fastmcp.client.auth import OAuth

STATEFUL_TOOL = "list_my_instances"
STATELESS_PROTOCOL = "2026-07-28"


async def check_legacy(url: str, auth: OAuth) -> None:
    async with Client(url, auth=auth, mode="legacy") as client:
        if client.initialize_result is None:
            raise RuntimeError("Legacy client did not complete an initialize handshake")
        if not client.transport.get_session_id():
            raise RuntimeError("Legacy client did not receive an MCP session ID")

        result = await client.call_tool(STATEFUL_TOOL)
        if not isinstance(result.data, list):
            raise RuntimeError(f"{STATEFUL_TOOL} returned an unexpected result type: {type(result.data).__name__}")

        print(f"PASS legacy: {client.protocol_version}, authenticated session and {STATEFUL_TOOL}")


async def check_stateless(url: str, auth: OAuth) -> None:
    async with Client(url, auth=auth, mode="auto") as client:
        if client.protocol_version != STATELESS_PROTOCOL:
            raise RuntimeError(f"Expected stateless protocol {STATELESS_PROTOCOL}, got {client.protocol_version}")

        created = await client.call_tool("create_session")
        session_id = created.data
        if not isinstance(session_id, str) or not session_id:
            raise RuntimeError("create_session did not return a session ID")
        try:
            result = await client.call_tool(STATEFUL_TOOL, {"session_id": session_id})
            if not isinstance(result.data, list):
                raise RuntimeError(f"{STATEFUL_TOOL} returned an unexpected result type: {type(result.data).__name__}")
        finally:
            await client.call_tool("end_session", {"session_id": session_id})

        print(f"PASS stateless: {client.protocol_version}, authenticated conversation and {STATEFUL_TOOL}")


async def run(url: str, mode: str) -> None:
    auth = OAuth()
    if mode in ("both", "legacy"):
        await check_legacy(url, auth)
    if mode in ("both", "stateless"):
        await check_stateless(url, auth)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:5000/mcp", help="MCP endpoint URL")
    parser.add_argument("--mode", choices=("both", "legacy", "stateless"), default="both")
    args = parser.parse_args()
    asyncio.run(run(args.url, args.mode))


if __name__ == "__main__":
    main()
