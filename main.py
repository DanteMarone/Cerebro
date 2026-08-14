"""Main entrypoint for Cerebro v2."""

import uvicorn
from cerebro.config import settings


def main() -> None:
    """Run the Cerebro v2 FastAPI application."""
    uvicorn.run(
        "cerebro.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
