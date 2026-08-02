"""Run the full application: `python -m hr_assistant`."""

import uvicorn

from .api import create_app
from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port, log_level="warning")


if __name__ == "__main__":
    main()
