#!/usr/bin/env bash
# Regenerate the dashboard from cached raw data. Fetch first if data/raw is empty.
set -euo pipefail
cd "$(dirname "$0")"
uv run python -m impact.cli
uv run python -c "
import json, pathlib
from impact.render import render
out = pathlib.Path('docs/index.html')
out.write_text(render(json.loads(pathlib.Path('data/scored.json').read_text())))
print(f'wrote {out} ({out.stat().st_size} bytes)')
"
