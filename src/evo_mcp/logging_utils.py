# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Shared logging helpers for Evo MCP tool operations."""

from __future__ import annotations

import logging
from typing import Any

from fastmcp import Context


def operation_extra(operation_id: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"operation_id": operation_id}
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def result_with_operation_id(operation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {"operation_id": operation_id, **payload}


async def log_operation_event(
    ctx: Context | None,
    logger: logging.Logger,
    message: str,
    operation_id: str,
    ctx_level: str = "info",
    **extra: Any,
) -> None:
    event_extra = operation_extra(operation_id, **extra)
    if ctx:
        await getattr(ctx, ctx_level)(message, extra=event_extra)
        return

    log_level = getattr(logging, ctx_level.upper(), logging.INFO)
    logger.log(log_level, message, extra=event_extra)


async def log_handled_failure(
    ctx: Context | None,
    logger: logging.Logger,
    message: str,
    operation_id: str,
    error: Exception,
    ctx_level: str = "error",
    **extra: Any,
) -> None:
    failure_extra = operation_extra(
        operation_id,
        error_type=type(error).__name__,
        error=str(error),
        **extra,
    )
    if ctx:
        await getattr(ctx, ctx_level)(message, extra=failure_extra)
        logger.debug("%s stack trace", message, exc_info=True, extra=failure_extra)
        return

    logger.exception(message, extra=failure_extra)
