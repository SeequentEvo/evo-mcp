# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Environment loading utilities for evo-mcp."""

from pathlib import Path

from dotenv import load_dotenv

_ENV_LOADED = False


def load_repo_env() -> None:
    """Load the repository .env file once if present."""
    global _ENV_LOADED

    if _ENV_LOADED:
        return

    env_path = Path(__file__).parent.parent.parent / ".env"
    load_dotenv(dotenv_path=env_path)
    _ENV_LOADED = True
