from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.runtime import ensure_runtime_dirs
from backend.app.db.migrations import migration_status


def main() -> None:
    ensure_runtime_dirs()
    status = migration_status()
    print(f"current_revision={status['current_revision']}")
    print(f"head_revision={status['head_revision']}")
    print(f"up_to_date={status['up_to_date']}")


if __name__ == "__main__":
    main()
