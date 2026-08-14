"""Import the temporary Markdown war room into the live Cerebro v2 database."""

import argparse
import asyncio
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cerebro import db  # noqa: E402
from cerebro.config import settings  # noqa: E402
from cerebro.transcript_import import import_warroom  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "transcript",
        type=Path,
        help="path to an archived Markdown war-room transcript",
    )
    parser.add_argument("--channel-id", default="warroom")
    return parser


async def run(transcript: Path, channel_id: str) -> dict:
    """Connect, import one snapshot, and return its summary."""
    await db.connect(db_path=settings.db_path)
    await db.migrate()
    try:
        result = await import_warroom(transcript.resolve(), channel_id=channel_id)
        return result.to_dict()
    finally:
        await db.close()


def main() -> None:
    """Run the importer and print a machine-readable summary."""
    args = build_parser().parse_args()
    summary = asyncio.run(run(args.transcript, args.channel_id))
    print(json.dumps(summary, sort_keys=True))


if __name__ == "__main__":
    main()
