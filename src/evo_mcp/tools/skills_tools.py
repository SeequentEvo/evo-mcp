# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tool for syncing evo-mcp skills to the user's local AI tool skills directory.
"""

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Platform → default skills directory (mirrors FastMCP vendor provider defaults)
PLATFORM_DIRS: dict[str, Path] = {
    "copilot": Path.home() / ".copilot" / "skills",
    "claude": Path.home() / ".claude" / "skills",
    "cursor": Path.home() / ".cursor" / "skills",
    "codex": Path.home() / ".codex" / "skills",
    "gemini": Path.home() / ".gemini" / "skills",
    "goose": Path.home() / ".config" / "agents" / "skills",
    "opencode": Path.home() / ".config" / "opencode" / "skills",
}


def register_skills_sync_tools(mcp, skills_folder: Path):
    """Register skill sync tools with the FastMCP server."""

    @mcp.tool()
    async def sync_skills(
        target_platform: str = "copilot",
        target_dir: str = "",
        skills: list[str] = [],
        overwrite: bool = False,
    ) -> dict:
        """Sync evo-mcp skills from this server to the user's local AI tool skills directory.

        Copies skill folders (each containing a SKILL.md) from the server's skills
        directory to the platform-specific local skills folder so that chat clients
        (Copilot, Claude, Cursor, etc.) can discover and use them.

        Args:
            target_platform: Destination platform. One of: copilot (default), claude,
                cursor, codex, gemini, goose, opencode, custom. When "custom", provide
                target_dir.
            target_dir: Absolute path to the target skills directory. Only used when
                target_platform is "custom".
            skills: List of skill names to sync (e.g. ["evo-object-discovery",
                "kriging-workflow"]). Leave empty to sync all available skills.
            overwrite: If True, replace existing skill directories at the destination.
                If False (default), existing skills are skipped.

        Returns:
            A summary with synced, skipped, and failed skill names plus the target path.
        """
        # Resolve target directory
        platform = target_platform.lower().strip()
        if platform == "custom":
            if not target_dir:
                return {
                    "error": "target_dir must be provided when target_platform is 'custom'.",
                    "synced": [],
                    "skipped": [],
                    "failed": [],
                }
            dest_root = Path(target_dir).expanduser().resolve()
        elif platform in PLATFORM_DIRS:
            dest_root = PLATFORM_DIRS[platform]
        else:
            valid = ", ".join(sorted(PLATFORM_DIRS)) + ", custom"
            return {
                "error": f"Unknown target_platform '{target_platform}'. Valid options: {valid}.",
                "synced": [],
                "skipped": [],
                "failed": [],
            }

        # Discover available skills in the server's skills folder
        if not skills_folder.exists():
            return {
                "error": f"Server skills folder not found at {skills_folder}.",
                "synced": [],
                "skipped": [],
                "failed": [],
            }

        available_skills = [
            d for d in skills_folder.iterdir()
            if d.is_dir() and (d / "SKILL.md").exists()
        ]

        # Filter to requested skills if specified
        if skills:
            requested = set(skills)
            available_names = {d.name for d in available_skills}
            unknown = requested - available_names
            if unknown:
                return {
                    "error": f"Unknown skill(s): {sorted(unknown)}. Available: {sorted(available_names)}.",
                    "synced": [],
                    "skipped": [],
                    "failed": [],
                }
            available_skills = [d for d in available_skills if d.name in requested]

        if not available_skills:
            return {
                "error": "No skills found in server skills folder.",
                "synced": [],
                "skipped": [],
                "failed": [],
            }

        # Ensure destination root exists
        try:
            dest_root.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return {
                "error": f"Could not create target directory '{dest_root}': {e}",
                "synced": [],
                "skipped": [],
                "failed": [],
            }

        synced: list[str] = []
        skipped: list[str] = []
        failed: list[dict] = []

        for skill_dir in sorted(available_skills, key=lambda d: d.name):
            skill_name = skill_dir.name
            dest = dest_root / skill_name

            if dest.exists() and not overwrite:
                skipped.append(skill_name)
                logger.debug("Skipping existing skill: %s", skill_name)
                continue

            try:
                if dest.exists() and overwrite:
                    shutil.rmtree(dest)
                shutil.copytree(skill_dir, dest)
                synced.append(skill_name)
                logger.info("Synced skill: %s -> %s", skill_name, dest)
            except Exception as e:
                logger.error("Failed to sync skill %s: %s", skill_name, e)
                failed.append({"skill": skill_name, "error": str(e)})

        return {
            "target_dir": str(dest_root),
            "synced": synced,
            "skipped": skipped,
            "failed": failed,
            "summary": (
                f"{len(synced)} synced, {len(skipped)} skipped, {len(failed)} failed."
            ),
        }
