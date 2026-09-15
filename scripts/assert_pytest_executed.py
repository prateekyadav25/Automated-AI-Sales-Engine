"""Run pytest once and fail if zero tests passed or the suite only skipped."""

from __future__ import annotations

import re
import subprocess
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: assert_pytest_executed.py <pytest args...>", file=sys.stderr)
        return 2
    result = subprocess.run(["pytest", *sys.argv[1:]], check=False, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    text = (result.stdout or "") + (result.stderr or "")
    if result.returncode == 5 or "collected 0 items" in text or "no tests ran" in text.lower():
        print("FAIL: pytest collected zero tests", file=sys.stderr)
        return 1
    passed = re.search(r"(\d+) passed", text)
    if not passed or int(passed.group(1)) < 1:
        print("FAIL: pytest passed zero tests (all skipped or empty)", file=sys.stderr)
        return 1
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
