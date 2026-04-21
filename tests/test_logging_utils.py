# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import logging
import unittest
from unittest.mock import AsyncMock, Mock

from evo_mcp.logging_utils import log_operation_event


class LogOperationEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_uses_context_when_available(self) -> None:
        ctx = Mock()
        ctx.info = AsyncMock()
        logger = Mock(spec=logging.Logger)

        await log_operation_event(
            ctx,
            logger,
            "Operation completed",
            "op-1",
            workspace_id="workspace-1",
        )

        ctx.info.assert_awaited_once_with(
            "Operation completed",
            extra={"operation_id": "op-1", "workspace_id": "workspace-1"},
        )
        logger.log.assert_not_called()

    async def test_falls_back_to_logger_without_context(self) -> None:
        logger = Mock(spec=logging.Logger)

        await log_operation_event(
            None,
            logger,
            "Validation failed",
            "op-2",
            ctx_level="warning",
            status="validation_failed",
        )

        logger.log.assert_called_once_with(
            logging.WARNING,
            "Validation failed",
            extra={"operation_id": "op-2", "status": "validation_failed"},
        )


if __name__ == "__main__":
    unittest.main()
