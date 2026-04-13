import re
from typing import Optional, Tuple

from kindr_app.models import User


def parse_login_identifier(raw: str) -> Tuple[str, str]:
    """
    Classify sign-in input. Returns ("email", lowercased) or ("phone", normalized digits/plus).
    Empty -> ("", "").
    """
    s = (raw or "").strip()
    if not s:
        return "", ""
    if "@" in s:
        return "email", s.lower()
    cleaned = re.sub(r"[\s\-\(\)]+", "", s)
    if not cleaned:
        return "", ""
    if cleaned.startswith("+"):
        return "phone", cleaned
    if cleaned.startswith("0") and len(cleaned) >= 10:
        return "phone", "+233" + cleaned[1:]
    return "phone", cleaned


def find_user_by_login_identifier(raw: str) -> Optional[User]:
    kind, value = parse_login_identifier(raw)
    if not value:
        return None
    if kind == "email":
        return User.query.filter_by(email=value).first()
    variants = {value}
    if value.startswith("+233") and len(value) > 4:
        variants.add("0" + value[4:])
    elif value.startswith("0") and len(value) >= 10:
        variants.add("+233" + value[1:])
    for v in variants:
        u = User.query.filter_by(phone=v).first()
        if u:
            return u
    return None
