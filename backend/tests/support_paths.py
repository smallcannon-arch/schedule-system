from pathlib import Path


TESTS = Path(__file__).resolve().parent
BACKEND = TESTS.parent
ROOT = BACKEND.parent
FIXTURES = TESTS / "fixtures"

if (ROOT / "index.html").is_file():
    ONLINE = ROOT
    FORMAL = ROOT
else:
    ONLINE = ROOT / "上線包"
    FORMAL = ROOT / "正式上線包"

SEPARATE_DEMO = ONLINE != FORMAL
