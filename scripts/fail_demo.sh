#!/usr/bin/env bash
# usage: bash scripts/fail_demo.sh push     -> commits + pushes a deliberately failing test (stops at PRE_BUILD)
#        bash scripts/fail_demo.sh revert   -> reverts that commit and pushes (final green run)
set -euo pipefail
case "${1:-}" in
  push)
    cat >> tests/test_features.py <<'PY'


def test_deliberate_failure_for_pipeline_demo():
    """Lab 4 Task 2 failure demo: this MUST fail so PRE_BUILD stops the pipeline."""
    assert 1 + 1 == 3, "DELIBERATE FAILURE: demonstrating that CI halts before training/registration"
PY
    git add tests/test_features.py
    git commit -m "Deliberate failing test to demonstrate CI halt (Lab 4 Task 2)"
    git push origin main
    git rev-parse HEAD > /tmp/lab4_fail_sha ;;
  revert)
    git revert --no-edit "$(cat /tmp/lab4_fail_sha)"
    git push origin main ;;
  *) echo "usage: $0 push|revert"; exit 1 ;;
esac
