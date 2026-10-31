import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["APP_ROOT"] = str(ROOT)
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="crm-test-")
os.environ["PRICES_FILE"] = str(ROOT / "backend" / "tests" / "prices.test.json")
os.environ.setdefault("DEEPSEEK_API_KEY", "")
sys.path.insert(0, str(ROOT / "backend"))
