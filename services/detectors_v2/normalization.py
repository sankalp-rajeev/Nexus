"""Fixed C2/C4 normalizations. No dataset-derived parameters."""
import re
import unicodedata


def _without_punctuation(text):
    # Replace punctuation/symbols with boundaries, avoiding accidental word joins.
    return "".join(" " if unicodedata.category(c)[0] in {"P", "S"} else c for c in text)


def argument_tokens(text: str) -> frozenset[str]:
    return frozenset(_without_punctuation(text.lower()).split())


def jaccard(a, b) -> float:
    return len(a & b) / len(a | b) if a or b else 1.0


def grounding_text(text: str) -> str:
    text = re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)
    text = unicodedata.normalize("NFKD", text.casefold())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(_without_punctuation(text).split())
