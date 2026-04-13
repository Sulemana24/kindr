import secrets
from datetime import datetime, timedelta, timezone

from werkzeug.security import check_password_hash, generate_password_hash

from kindr_app.extensions import db
from kindr_app.models import OtpChallenge, User

OTP_PURPOSES = frozenset(
    {"register", "login", "oauth_complete", "campaign_register", "reset_password"}
)
MAX_ATTEMPTS = 5
TTL_MINUTES = 10


def _now():
    return datetime.now(timezone.utc)


def _as_utc(dt: datetime) -> datetime:
    """SQLite returns naive datetimes; treat them as UTC for comparisons."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def generate_otp_code() -> str:
    return f"{secrets.randbelow(900000) + 100000:06d}"


def hash_code(code: str) -> str:
    # pbkdf2 is portable; short OTP strings work reliably across platforms
    return generate_password_hash(code, method="pbkdf2:sha256", salt_length=16)


def verify_code_hash(stored_hash: str, code: str) -> bool:
    return check_password_hash(stored_hash, code)


def create_otp(user_id: int, purpose: str) -> str:
    if purpose not in OTP_PURPOSES:
        raise ValueError("invalid purpose")
    OtpChallenge.query.filter_by(user_id=user_id, purpose=purpose, consumed=False).delete()
    code = generate_otp_code()
    row = OtpChallenge(
        user_id=user_id,
        purpose=purpose,
        code_hash=hash_code(code),
        expires_at=_now() + timedelta(minutes=TTL_MINUTES),
    )
    db.session.add(row)
    db.session.commit()
    return code


def invalidate_pending(user_id: int, purpose: str) -> None:
    OtpChallenge.query.filter_by(user_id=user_id, purpose=purpose, consumed=False).delete()
    db.session.commit()


def verify_otp(user: User, code: str, purpose: str) -> tuple[bool, str]:
    if purpose not in OTP_PURPOSES:
        return False, "Invalid verification type."
    challenge = (
        OtpChallenge.query.filter_by(user_id=user.id, purpose=purpose, consumed=False)
        .order_by(OtpChallenge.created_at.desc())
        .first()
    )
    if not challenge:
        return False, "No verification code found. Request a new code."
    if _as_utc(challenge.expires_at) < _now():
        challenge.consumed = True
        db.session.commit()
        return False, "This code has expired. Request a new one."
    if challenge.attempts >= MAX_ATTEMPTS:
        return False, "Too many failed attempts. Request a new code."
    challenge.attempts += 1
    db.session.commit()
    if not verify_code_hash(challenge.code_hash, code.strip()):
        db.session.commit()
        return False, "Invalid verification code."
    challenge.consumed = True
    db.session.commit()
    return True, ""
