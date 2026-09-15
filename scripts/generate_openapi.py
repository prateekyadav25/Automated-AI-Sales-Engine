"""Export FastAPI OpenAPI JSON and a generated TypeScript types module."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from app.main import app  # noqa: E402

OPENAPI_PATH = ROOT / "packages" / "types" / "openapi.json"
TS_PATH = ROOT / "packages" / "types" / "src" / "generated.ts"


def render(spec: dict) -> tuple[str, str]:
    openapi_text = json.dumps(spec, indent=2, sort_keys=True) + "\n"
    paths = spec.get("paths") or {}
    schemas = ((spec.get("components") or {}).get("schemas")) or {}
    lines = [
        "/* Generated from FastAPI OpenAPI. Do not edit by hand. */",
        "export type GeneratedPaths = {",
    ]
    for path in sorted(paths):
        methods = ", ".join(sorted(paths[path].keys()))
        lines.append(f"  {json.dumps(path)}: {json.dumps(methods)};")
    lines.append("};")
    lines.append("")
    lines.append("export const generatedPathCount = " + str(len(paths)) + ";")
    lines.append("export const generatedSchemaNames = [")
    for name in sorted(schemas):
        lines.append(f"  {json.dumps(name)},")
    lines.append("] as const;")
    lines.append("")
    return openapi_text, "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    spec = app.openapi()
    openapi_text, ts_text = render(spec)
    if args.check:
        if not OPENAPI_PATH.exists() or not TS_PATH.exists():
            print("generated OpenAPI artifacts are missing; run scripts/generate_openapi.py")
            return 1
        existing_openapi = OPENAPI_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        existing_ts = TS_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
        if existing_openapi != openapi_text or existing_ts != ts_text:
            print("OpenAPI drift detected; run python scripts/generate_openapi.py")
            return 1
        print("OpenAPI artifacts are current")
        return 0
    OPENAPI_PATH.parent.mkdir(parents=True, exist_ok=True)
    TS_PATH.parent.mkdir(parents=True, exist_ok=True)
    OPENAPI_PATH.write_text(openapi_text, encoding="utf-8", newline="\n")
    TS_PATH.write_text(ts_text, encoding="utf-8", newline="\n")
    print(f"wrote {OPENAPI_PATH} and {TS_PATH} ({len(spec.get('paths') or {})} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
