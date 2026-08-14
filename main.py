"""Main entrypoint for Cerebro v2."""

import signal
import uvicorn
from cerebro.config import settings


def main() -> None:
    """Run the Cerebro v2 FastAPI application with clean signal handling."""
    config = uvicorn.Config(
        "cerebro.api.app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="info",
    )
    server = uvicorn.Server(config)

    def _handle_exit(sig, frame):
        server.should_exit = True

    for sig_name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, sig_name):
            try:
                signal.signal(getattr(signal, sig_name), _handle_exit)
            except (ValueError, AttributeError):
                pass

    server.run()


if __name__ == "__main__":
    main()
