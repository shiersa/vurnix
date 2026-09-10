#!/usr/bin/env bash
# vurnix self-check — the honest gate eats its own dogfood.
#
# The full test suite must pass, the SHIPPED code must compile with zero phantom
# imports, and the suite must keep a minimum honest test count. (Running the
# composite gate on the repo ROOT would flag our intentionally-broken test
# fixtures — being flagged is what those fixtures are for.)
set -e
cd "$(dirname "$0")/.."

echo "== pytest =="
uv run --with pytest python -m pytest tests/ -q

echo "== vurnix compile src =="
PYTHONPATH=src python3 -m vurnix.cli compile src

echo "== vurnix phantom src (must be empty) =="
out=$(PYTHONPATH=src python3 -m vurnix.cli phantom src)
if [ -n "$out" ]; then
  echo "$out"
  echo "SELFCHECK FAIL: phantom findings in shipped code"
  exit 1
fi
echo "(clean)"

echo "== vurnix coverage tests (floor 60) =="
n=$(PYTHONPATH=src python3 -m vurnix.cli coverage tests)
echo "count=$n"
if [ "$n" -lt 60 ]; then
  echo "SELFCHECK FAIL: honest test count $n below floor 60"
  exit 1
fi

echo "SELFCHECK PASS"
