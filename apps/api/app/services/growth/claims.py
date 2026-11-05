"""Find statements in a caption that the approved facts do not support.

Numbers, percentages, rankings, guarantees, awards, and certifications must
appear in an approved fact. Sensitive terms from the strategy always send the
creative to a person, even when a fact supports them.
"""

from __future__ import annotations

import re

CLAIM_TOKEN = re.compile(
    r"(?<![\w#/@])(\d[\d,]*(?:\.\d+)?\s?(?:%|\+|x(?!\w)|k(?!\w)|m(?!\w))?)"
    r"|(?<!\w)(#1)(?!\d)"
    r"|\b(best|number one|leading|top-rated|fastest|largest|only|guarantee[sd]?|award[- ]winning|award|certified|"
    r"trusted by|world[- ]class|cheapest|unbeatable|proven)\b",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://\S+")
_TAG = re.compile(r"(?<!\w)(?:#(?!\d+(?!\w))\w+|@\w+)")


def _strip(text: str) -> str:
    return _TAG.sub(" ", _URL.sub(" ", text or ""))


def _key(token: str) -> str:
    return re.sub(r"[\s,]", "", token.casefold())


def claim_tokens(text: str) -> list[str]:
    seen: list[str] = []
    for match in CLAIM_TOKEN.finditer(_strip(text)):
        token = match.group(0).strip()
        if token and _key(token) not in {_key(item) for item in seen}:
            seen.append(token)
    return seen


def check_claims(caption: str, *, support: list[str], review_terms: list[str]) -> dict:
    supported = {_key(token) for text in support for token in claim_tokens(text)}
    checked = [{"token": token, "supported": _key(token) in supported} for token in claim_tokens(caption)]
    body = _strip(caption)
    sensitive = sorted({term for term in review_terms if term and re.search(rf"(?<![\w]){re.escape(term)}(?![\w])", body, re.IGNORECASE)})
    return {
        "checked": checked,
        "unsupported": [item["token"] for item in checked if not item["supported"]],
        "sensitive": sensitive,
        "rule": "Every number, ranking, award, or guarantee must appear in an approved fact. Sensitive terms always need a person.",
    }
