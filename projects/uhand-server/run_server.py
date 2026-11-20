"""Run directly from an offline source release on the Pi."""
from pathlib import Path
import sys
root = Path(__file__).resolve().parent
sys.path.insert(0, str(root / "src"))
shared_source = root.parents[1] / "shared/uhand-server-lifecycle/src"
if shared_source.is_dir():
    sys.path.insert(0, str(shared_source))
from uhand_server.__main__ import main
if __name__=="__main__":
    main()
