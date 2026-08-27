from __future__ import annotations

import hashlib
import re


def canonical_text(title: str, body: str) -> str:
    text = f"{title}\n{body}".lower().strip()
    return re.sub(r"\s+", " ", text)


def fingerprint(title: str, body: str) -> str:
    return hashlib.sha256(canonical_text(title, body).encode()).hexdigest()
