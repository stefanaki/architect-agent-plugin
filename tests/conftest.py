"""Import paths for the tests: the Gazette harness and the scripts of the regulations skill."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "plugins" / "architect-agent" / "skills" / "regulations"
sys.path[:0] = [str(REPO / "tools" / "gazette" / "lib"), str(SKILL / "scripts")]
