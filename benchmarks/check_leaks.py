from __future__ import annotations

import re
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
drive = re.findall(r"[A-Za-z]:[\\/][^\"]*", text)
hex64 = re.findall(r"\b[0-9a-f]{64}\b", text)
leaks = bool(drive) or bool(hex64) or ("AppData" in text) or ("mazen" in text.lower())
print(path.name, "LEAK" if leaks else "clean", drive[:2], hex64[:2])
