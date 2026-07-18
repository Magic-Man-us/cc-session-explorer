"""Command line entry point for refreshing the priced usage archive."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from cc_session_explorer.ingest.db import connect, default_db_path
from cc_session_explorer.ingest.ingest import ingest
from cc_session_explorer.ingest.rollup import derive_rollups
from cc_session_explorer.ingest.usage import CCLEDGER_DB, import_ccledger


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cc-session-history",
        description="Ingest transcripts and price them into the usage archive.",
    )
    parser.add_argument("--db", default=str(default_db_path()), help="store SQLite path")
    parser.add_argument(
        "--ccledger",
        default=str(CCLEDGER_DB),
        help="retired ccledger database to import usage from, if it is still around",
    )
    args = parser.parse_args()
    conn = connect(Path(args.db))
    try:
        report = ingest(conn)
        legacy_added = import_ccledger(conn, Path(args.ccledger))
        derive_rollups(conn)  # the legacy rows land after ingest folded its own
    finally:
        conn.close()
    sys.stdout.write(
        f"Usage archive refreshed: {report.usage_priced} priced from "
        f"{report.records_inserted} new records, {legacy_added} legacy ccledger rows added.\n"
    )


if __name__ == "__main__":
    main()
