"""Export the OpenAPI document (used to generate the TypeScript client).

Usage: uv run python apps/api/scripts/export_openapi.py packages/api-client/openapi.json
"""

from __future__ import annotations

import json
import os
import sys

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("LOG_LEVEL", "ERROR")

from app.main import create_app


def main() -> None:
    out = sys.argv[1] if len(sys.argv) > 1 else "openapi.json"
    spec = create_app().openapi()
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(spec, fh, indent=2, sort_keys=False)
        fh.write("\n")
    print(f"wrote {out} ({len(spec.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
