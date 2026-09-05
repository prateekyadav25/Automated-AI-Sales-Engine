$ErrorActionPreference = "Stop"
Push-Location "$PSScriptRoot\..\apps\api"
python -m pip install -e ".[dev]"
ruff check app tests
pytest
Pop-Location
Push-Location "$PSScriptRoot\..\apps\web"
pnpm lint
pnpm exec tsc --noEmit
pnpm test
pnpm build
Pop-Location
