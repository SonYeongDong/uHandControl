"""Run the release's local regression suites; network tests use loopback."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    "projects/uhand-client-module/tests", "projects/uhand-motion-creator/tests",
    "projects/uhand-virtual-server/tests", "projects/uhand-server/tests",
    "shared/uhand-model/tests", "shared/tests",
)


def main():
    env = dict(os.environ, PYTHONPATH=str(ROOT / "projects/uhand-server/src"),
               PYTHONIOENCODING="utf-8")
    failed = False
    for suite in SUITES:
        print(f"\n{suite}", flush=True)
        result = subprocess.run([sys.executable, "-B", "-m", "unittest", "discover",
                                 "-s", suite, "-p", "test_*.py"], cwd=ROOT, env=env)
        failed |= result.returncode != 0
    return int(failed)


if __name__ == "__main__":
    sys.exit(main())
