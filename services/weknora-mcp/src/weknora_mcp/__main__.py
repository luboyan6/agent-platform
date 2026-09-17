"""Command-line entry point for the standalone service."""

from __future__ import annotations

import uvicorn

from weknora_mcp.app import create_application
from weknora_mcp.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        create_application(settings),
        host=settings.mcp_host,
        port=settings.mcp_port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
