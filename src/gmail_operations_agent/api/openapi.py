"""The API's OpenAPI schema, the source of the frontend's TypeScript types.

`python -m gmail_operations_agent.api.openapi` rewrites frontend/openapi.json, and
`npm run gen:api` turns it into types. A test fails when the file is out of date.
"""

import json
import sys
from pathlib import Path

from fastapi import FastAPI

from gmail_operations_agent import __version__
from gmail_operations_agent.api.app import TITLE
from gmail_operations_agent.api.routes import router

SCHEMA_FILE = Path(__file__).parents[3] / "frontend" / "openapi.json"


def render() -> str:
    app = FastAPI(title=TITLE, version=__version__)
    app.include_router(router)
    return json.dumps(app.openapi(), indent=2, ensure_ascii=False) + "\n"


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else SCHEMA_FILE
    path.write_text(render(), "utf-8", newline="\n")
    print(f"Wrote {path}")


if __name__ == "__main__":
    main()
