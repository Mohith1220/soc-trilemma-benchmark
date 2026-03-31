"""Server entry point for openenv validate / uv run server compatibility."""
from __future__ import annotations

import uvicorn

from app.app import app  # noqa: F401 — re-export for uvicorn


def main() -> None:
    """Start the uvicorn server. Called by `uv run server` and pyproject.toml scripts."""
    uvicorn.run("app.app:app", host="0.0.0.0", port=7860, reload=False)


if __name__ == "__main__":
    main()
