"""Debug launcher: sync the single test bank/date under F5.

No CLI subcommands. Tables are created automatically when missing (see
``sync_one``), so a fresh database works on the first run. To target a
different bank/date, edit the constants below.
"""
from datetime import date
from pathlib import Path

import sys

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from bank_etl.config import load_dataset
from bank_etl.etl import sync_one
from bank_etl.postgres import create_ai_engine
from bank_etl.sqlserver import create_source_engine

# The single bank/date under test.
TEST_BANK_ID = -48858
TEST_AS_OF = date(2026, 6, 30)

if __name__ == "__main__":
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    # Use a path relative to this file, not the current working directory, so
    # F5 works when VS Code launches from the repository root.
    spec = load_dataset(Path(__file__).resolve().parent / "configs" / "dashboard.yaml")
    source = create_source_engine()
    ai = create_ai_engine()
    try:
        result = sync_one(source, ai, spec, TEST_BANK_ID, TEST_AS_OF)
        print(result)
    finally:
        source.dispose()
        ai.dispose()
