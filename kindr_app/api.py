import os
import secrets
import threading
from datetime import datetime, time, timezone

from flask import Blueprint, current_app, jsonify, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user
from flask_wtf.csrf import generate_csrf
from werkzeug.utils import secure_filename

from kindr_app.campaign_utils import (
    campaign_to_public_dict,
    normalize_category_slug,
    user_payload,
)
from kindr_app.donations_service import new_paystack_reference
from kindr_app.extensions import csrf, db
from kindr_app.auth_utils import find_user_by_login_identifier
from kindr_app.messaging import (
    deliver_otp_code,
    send_email_otp,
    send_sms_africastalking,
    send_support_ai_escalation,
)
from kindr_app.models import Campaign, User
from kindr_app.otp_util import create_otp, verify_otp
from kindr_app.paystack_client import paystack_initialize
from kindr_app.gemini_client import gemini_generate

bp = Blueprint("api", __name__)

_KINDR_AI_SYSTEM = """You are a helpful assistant for Kindr, a crowdfunding platform focused on charitable causes, community projects, and social impact (Ghana and beyond). Answer clearly and accurately based on general knowledge about crowdfunding best practices. If asked for account-specific data, payment details, passwords, or anything you cannot verify, say you cannot access that and suggest using official Kindr support or in-app flows. Keep answers concise unless the user asks for detail. Never invent legal guarantees or claim Kindr policies unless they match common crowdfunding norms; when unsure, suggest checking the Help center or Terms on the site.

Escalation (use rarely): If you truly cannot help with the question in any useful way—not routine refusals of secrets or private data, but cases where you have no substantive answer—end your reply with a new line containing exactly this token and nothing after it:
ESCALATE_TO_TEAM
If you can help at all, do not include that token."""

_ESCALATE_MARKER = "ESCALATE_TO_TEAM"

_MAX_AI_USER_CHARS = 4000
_MAX_AI_HISTORY_ITEMS = 24


def _build_gemini_contents(history: list, message: str) -> list[dict]:
    """Turn client history + new message into Gemini `contents` (roles user/model)."""
    out: list[dict] = []
    for item in history:
        if not isinstance(item, dict):
            continue
        role = (item.get("role") or "").strip().lower()
        text = (item.get("text") or "").strip()
        if not text or len(text) > _MAX_AI_USER_CHARS:
            continue
        if role == "user":
            out.append({"role": "user", "parts": [{"text": text}]})
        elif role in ("model", "assistant"):
            out.append({"role": "model", "parts": [{"text": text}]})
    msg = message.strip()
    if msg:
        out.append({"role": "user", "parts": [{"text": msg}]})
    return out[-_MAX_AI_HISTORY_ITEMS:]


def _strip_escalation_marker(reply: str) -> tuple[str, bool]:
    """Remove trailing ESCALATE_TO_TEAM line; returns (cleaned_reply, did_escalate)."""
    r = (reply or "").rstrip()
    if not r:
        return "", False
    lines = r.splitlines()
    if lines and lines[-1].strip() == _ESCALATE_MARKER:
        cleaned = "\n".join(lines[:-1]).rstrip()
        return cleaned, True
    if r.strip() == _ESCALATE_MARKER:
        return "", True
    return r, False


def _queue_ai_escalation_email(
    app,
    user_question: str,
    reason: str,
    *,
    error_or_model_detail: str | None = None,
    ai_reply_excerpt: str | None = None,
) -> None:
    vemail = None
    vname = None
    if current_user.is_authenticated:
        vemail = getattr(current_user, "email", None)
        vname = getattr(current_user, "name", None)

    support_to = (app.config.get("SUPPORT_EMAIL") or "").strip()

    def run() -> None:
        with app.app_context():
            ok, err = send_support_ai_escalation(
                app,
                support_to=support_to,
                user_question=user_question,
                reason=reason,
                visitor_email=vemail,
                visitor_name=vname,
                error_or_model_detail=error_or_model_detail,
                ai_reply_excerpt=ai_reply_excerpt,
            )
            if not ok:
                app.logger.warning("AI escalation email failed: %s", err)

    threading.Thread(target=run, daemon=True).start()


def _json_error(message: str, code: int = 400):
    return jsonify({"message": message}), code


_ALLOWED_IMAGE_EXTS = {"jpg", "jpeg", "png", "webp", "gif"}


def _allowed_image(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in _ALLOWED_IMAGE_EXTS


def _campaign_has_ended(c: Campaign) -> bool:
    def as_utc(dt: datetime | None) -> datetime | None:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    now = datetime.now(timezone.utc)
    end_dt = as_utc(c.end_date)
    if (end_dt is not None) and (end_dt <= now):
        return True
    return float(c.raised_amount or 0) >= float(c.goal_amount or 0)


def _auto_close_campaign(c: Campaign) -> bool:
    if bool(getattr(c, "is_closed", False)):
        return False
    if not _campaign_has_ended(c):
        return False
    c.is_closed = True
    if (c.status or "") == "accepted":
        c.status = "completed"
    return True


@bp.get("/auth/oauth-pending")
def oauth_pending():
    uid = session.get("oauth_pending_user_id")
    if not uid:
        return jsonify({"pending": False})
    user = db.session.get(User, uid)
    if not user:
        session.pop("oauth_pending_user_id", None)
        return jsonify({"pending": False})
    return jsonify(
        {
            "pending": True,
            "email": user.email,
            "purpose": "oauth_complete",
        }
    )


@bp.get("/auth/me")
def me():
    if not current_user.is_authenticated:
        return jsonify({"user": None})
    return jsonify({"user": user_payload(current_user)})


@bp.get("/auth/csrf-token")
def csrf_token_refresh():
    return jsonify({"csrf_token": generate_csrf()})


@bp.post("/auth/register")
def register():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip() or None

    if not name or not email or not password:
        return _json_error("Name, email, and password are required.")
    if len(password) < 8:
        return _json_error("Password must be at least 8 characters.")
    if User.query.filter_by(email=email).first():
        return _json_error("An account with this email already exists.")

    user = User(email=email, name=name, phone=phone, is_active=False)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    code = create_otp(user.id, "register")
    ok_send, err_detail, hint = deliver_otp_code(
        current_app,
        user,
        code,
        f"Your Kindr code is {code}. Valid 10 minutes.",
    )
    if not ok_send:
        return _json_error(
            f"Could not send verification code: {err_detail}",
            500,
        )

    payload = {
        "requires_otp": True,
        "purpose": "register",
        "email": email,
        "message": hint,
    }
    if current_app.debug and (
        current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
    ):
        payload["dev_otp"] = code
    return jsonify(payload)


@bp.post("/auth/login")
def login():
    data = request.get_json(silent=True) or {}
    raw_id = (
        data.get("email")
        or data.get("identifier")
        or data.get("login")
        or data.get("phone")
        or ""
    )
    raw_id = (raw_id if isinstance(raw_id, str) else str(raw_id)).strip()
    password = data.get("password") or ""
    if not raw_id or not password:
        return _json_error("Enter your email or phone and password.")

    user = find_user_by_login_identifier(raw_id)
    if not user or not user.check_password(password):
        return _json_error("Invalid email/phone or password.", 401)

    if getattr(user, "is_suspended", False):
        return _json_error("This account has been suspended. Contact support if you think this is a mistake.", 403)

    if not user.is_active:
        code = create_otp(user.id, "register")
        ok_send, err_detail, hint = deliver_otp_code(
            current_app,
            user,
            code,
            f"Your Kindr verification code is {code}. Valid 10 minutes.",
        )
        if not ok_send:
            return _json_error(
                f"Could not send verification code: {err_detail}",
                500,
            )
        payload = {
            "requires_otp": True,
            "purpose": "register",
            "email": user.email,
            "message": hint,
        }
        if current_app.debug and (
            current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
        ):
            payload["dev_otp"] = code
        return jsonify(payload)

    code = create_otp(user.id, "login")
    ok_send, err_detail, hint = deliver_otp_code(
        current_app,
        user,
        code,
        f"Your Kindr login code is {code}. Valid 10 minutes.",
    )
    if not ok_send:
        return _json_error(
            f"Could not send verification code: {err_detail}",
            500,
        )

    payload = {
        "requires_otp": True,
        "purpose": "login",
        "email": user.email,
        "message": hint,
    }
    if current_app.debug and (
        current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
    ):
        payload["dev_otp"] = code
    return jsonify(payload)


@bp.post("/auth/verify-otp")
def verify_otp_route():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    purpose = (data.get("purpose") or "").strip()

    if not code or purpose not in ("register", "login", "oauth_complete", "campaign_register"):
        return _json_error("Code and a valid purpose are required.")

    user = None
    if purpose == "campaign_register":
        if not current_user.is_authenticated:
            return _json_error("Sign in first.", 401)
        user = current_user
    elif email:
        user = User.query.filter_by(email=email).first()
        if not user:
            return _json_error("No account found for this email.", 404)
    else:
        return _json_error("Email is required for this verification step.")

    ok, msg = verify_otp(user, code, purpose)
    if not ok:
        return _json_error(msg, 400)

    if getattr(user, "is_suspended", False):
        if purpose == "campaign_register":
            return _json_error("This account has been suspended.", 403)
        if purpose in ("register", "login", "oauth_complete"):
            return _json_error("This account has been suspended. Contact support if you think this is a mistake.", 403)

    if purpose == "register":
        user.is_active = True
        db.session.commit()
        login_user(user, remember=False)
        session.permanent = True
        session.pop("oauth_pending_user_id", None)
        return jsonify({"ok": True, "user": user_payload(user)})

    if purpose == "login":
        login_user(user, remember=False)
        session.permanent = True
        session.pop("oauth_pending_user_id", None)
        return jsonify({"ok": True, "user": user_payload(user)})

    if purpose == "oauth_complete":
        login_user(user, remember=False)
        session.permanent = True
        session.pop("oauth_pending_user_id", None)
        return jsonify({"ok": True, "user": user_payload(user)})

    if purpose == "campaign_register":
        session["campaign_otp_ok"] = True
        return jsonify({"ok": True, "message": "You can submit your campaign."})

    return _json_error("Unknown state.", 500)


@bp.post("/auth/resend-otp")
def resend_otp():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    purpose = (data.get("purpose") or "").strip()
    if not email or purpose not in ("register", "login", "oauth_complete"):
        return _json_error("Email and purpose are required.")

    user = User.query.filter_by(email=email).first()
    if not user:
        return _json_error("No account found.", 404)

    code = create_otp(user.id, purpose)
    ok_send, err_detail, _hint = deliver_otp_code(
        current_app,
        user,
        code,
        f"Your Kindr code is {code}. Valid 10 minutes.",
    )
    if not ok_send:
        return _json_error(
            f"Could not send verification code: {err_detail}",
            500,
        )
    payload = {"message": "A new code was sent."}
    if current_app.debug and (
        current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
    ):
        payload["dev_otp"] = code
    return jsonify(payload)


@bp.post("/auth/request-password-reset")
def request_password_reset():
    data = request.get_json(silent=True) or {}
    identifier = (data.get("identifier") or data.get("email") or "").strip()
    if not identifier:
        return _json_error("Enter your email or phone.")
    user = find_user_by_login_identifier(identifier)
    # Avoid account enumeration: always return success-like response.
    if not user:
        return jsonify({"message": "If the account exists, a reset code has been sent."})
    code = create_otp(user.id, "reset_password")
    ok, err = send_email_otp(current_app, user.email, code, user.name)
    if not ok:
        return _json_error(f"Could not send reset code: {err}", 500)
    payload = {
        "message": "If the account exists, a reset code has been sent.",
        "email": user.email,
    }
    if current_app.debug and (
        current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
    ):
        payload["dev_otp"] = code
    return jsonify(payload)


@bp.post("/auth/reset-password")
def reset_password():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""
    if not email or not code or not new_password:
        return _json_error("Email, code, and new password are required.")
    if len(new_password) < 8:
        return _json_error("Password must be at least 8 characters.")
    user = User.query.filter_by(email=email).first()
    if not user:
        return _json_error("No account found for this email.", 404)
    if getattr(user, "is_suspended", False):
        return _json_error("This account has been suspended. Contact support if you think this is a mistake.", 403)
    ok, msg = verify_otp(user, code, "reset_password")
    if not ok:
        return _json_error(msg, 400)
    user.set_password(new_password)
    db.session.commit()
    return jsonify({"ok": True, "message": "Password changed successfully. Please sign in."})


@csrf.exempt
@bp.post("/auth/logout")
def logout():
    logout_user()
    session.clear()
    resp = jsonify({"ok": True})
    resp.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "session"))
    resp.delete_cookie("remember_token")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.post("/auth/send-campaign-otp")
@login_required
def send_campaign_otp():
    code = create_otp(current_user.id, "campaign_register")
    ok, err = send_email_otp(
        current_app, current_user.email, code, current_user.name
    )
    if not ok:
        return _json_error(f"Could not send verification email: {err}", 500)
    if current_user.phone:
        send_sms_africastalking(
            current_app,
            current_user.phone,
            f"Your Kindr campaign verification code is {code}. Valid 10 minutes.",
        )
    payload = {"message": "Verification code sent to your email or phone."}
    if current_app.debug and (
        current_app.config.get("SHOW_DEV_OTP") or not current_app.config.get("MAIL_SERVER")
    ):
        payload["dev_otp"] = code
    return jsonify(payload)


@bp.get("/campaigns")
def list_campaigns():
    rows = Campaign.query.filter_by(status="accepted").order_by(Campaign.created_at.desc()).all()
    changed = False
    live_rows = []
    for c in rows:
        if _auto_close_campaign(c):
            changed = True
            continue
        if not bool(getattr(c, "is_closed", False)):
            live_rows.append(c)
    if changed:
        db.session.commit()
    return jsonify({"campaigns": [campaign_to_public_dict(c) for c in live_rows]})


@bp.get("/stats")
def public_stats():
    rows = Campaign.query.filter_by(status="accepted").all()
    campaigns_count = len(rows)
    total_raised = float(sum((c.raised_amount or 0) for c in rows))
    total_donors = int(sum((c.donor_count or 0) for c in rows))
    return jsonify(
        {
            "total_raised": total_raised,
            "campaigns_count": campaigns_count,
            "donors_count": total_donors,
        }
    )


@bp.post("/paystack/initialize")
def paystack_initialize_donation():
    data = request.get_json(silent=True) or {}
    try:
        campaign_id = int(data.get("campaign_id"))
    except (TypeError, ValueError):
        return _json_error("Invalid campaign.")
    try:
        amount = float(data.get("amount"))
    except (TypeError, ValueError):
        return _json_error("Enter a valid amount.")
    if amount < 1:
        return _json_error("Minimum donation is 1 GHS.")

    email = (data.get("email") or "").strip().lower()
    if not email:
        return _json_error("Email is required for checkout.")

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return _json_error("Campaign not found.", 404)
    if _auto_close_campaign(campaign):
        db.session.commit()
    if campaign.status != "accepted" or bool(getattr(campaign, "is_closed", False)):
        return _json_error("This campaign is closed and no longer accepts donations.", 400)

    sk = current_app.config.get("PAYSTACK_SECRET_KEY")
    cb = current_app.config.get("PAYSTACK_CALLBACK_URL")
    pk = current_app.config.get("PAYSTACK_PUBLIC_KEY") or ""
    if not sk or not cb:
        return _json_error(
            "Online payments are not configured. Set PAYSTACK_SECRET_KEY and "
            "PAYSTACK_CALLBACK_URL on the server.",
            503,
        )

    ref = new_paystack_reference()
    minor = int(round(amount * 100))
    meta = {"campaign_id": str(campaign_id), "payer_email": email}
    if current_user.is_authenticated:
        meta["donor_user_id"] = current_user.id

    out = paystack_initialize(
        sk,
        email,
        minor,
        "GHS",
        ref,
        cb,
        meta,
    )
    if not out or not out.get("status"):
        msg = (out or {}).get("message") if isinstance(out, dict) else None
        return _json_error(msg or "Could not start Paystack checkout.", 502)

    pay_data = out.get("data") or {}
    auth_url = pay_data.get("authorization_url")
    if not auth_url:
        return _json_error("Paystack did not return a checkout URL.", 502)

    return jsonify(
        {
            "authorization_url": auth_url,
            "reference": pay_data.get("reference") or ref,
            "public_key": pk,
        }
    )


@bp.post("/campaigns")
@login_required
def create_campaign():
    if not current_user.is_active:
        return _json_error(
            "Only verified accounts can create campaigns. Complete email verification first.",
            403,
        )
    if not session.get("campaign_otp_ok"):
        return _json_error(
            "Verify the security code before registering a campaign.", 403
        )

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    category = (data.get("category") or "").strip()
    goal_raw = data.get("goal_amount")
    image_url = (data.get("image_url") or "").strip() or None
    description = (data.get("description") or "").strip()
    start_date_raw = (data.get("start_date") or "").strip()
    end_date_raw = (data.get("end_date") or "").strip()

    if not title or not category or not description:
        return _json_error("Title, category, and description are required.")
    if not start_date_raw or not end_date_raw:
        return _json_error("Start date and completion date are required.")
    try:
        goal_amount = float(goal_raw)
    except (TypeError, ValueError):
        return _json_error("Goal amount must be a number.")
    if goal_amount <= 0:
        return _json_error("Goal amount must be positive.")
    try:
        start_date = datetime.combine(datetime.strptime(start_date_raw, "%Y-%m-%d").date(), time.min)
        start_date = start_date.replace(tzinfo=timezone.utc)
        end_date = datetime.combine(datetime.strptime(end_date_raw, "%Y-%m-%d").date(), time.max)
        end_date = end_date.replace(tzinfo=timezone.utc)
    except ValueError:
        return _json_error("Dates must be valid and use YYYY-MM-DD format.")
    if end_date <= start_date:
        return _json_error("Completion date must be after creation date.")

    cat_slug = normalize_category_slug(category)
    c = Campaign(
        user_id=current_user.id,
        title=title,
        category=cat_slug,
        goal_amount=goal_amount,
        raised_amount=0.0,
        donor_count=0,
        status="pending_review",
        start_date=start_date,
        end_date=end_date,
        is_closed=False,
        image_url=image_url,
        description=description,
    )
    db.session.add(c)
    db.session.commit()
    session.pop("campaign_otp_ok", None)
    return jsonify({"ok": True, "id": c.id, "message": "Campaign registered."})


@bp.post("/uploads/campaign-image")
@login_required
def upload_campaign_image():
    f = request.files.get("image")
    if not f or not f.filename:
        return _json_error("Please choose an image file.")
    if not _allowed_image(f.filename):
        return _json_error("Only jpg, jpeg, png, webp, and gif are allowed.")

    filename = secure_filename(f.filename)
    ext = filename.rsplit(".", 1)[1].lower()
    unique = f"campaign_{current_user.id}_{secrets.token_hex(8)}.{ext}"
    rel = os.path.join("uploads", "campaigns", unique)
    abs_path = os.path.join(current_app.static_folder, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    f.save(abs_path)
    return jsonify({"url": url_for("static", filename=rel)})


@bp.post("/ai/chat")
def ai_chat():
    """Public FAQ-style chat; API key stays server-side. CSRF required."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return _json_error("Message is required.")
    if len(message) > _MAX_AI_USER_CHARS:
        return _json_error("Message is too long.")

    history = data.get("history")
    if not isinstance(history, list):
        history = []

    app_obj = current_app._get_current_object()
    api_key = app_obj.config.get("GEMINI_API_KEY")
    if not api_key:
        _queue_ai_escalation_email(
            app_obj,
            message,
            "assistant_unavailable_no_gemini_key",
        )
        return _json_error("This feature is temporarily unavailable.", 503)

    context = (data.get("context") or "").strip()
    system = _KINDR_AI_SYSTEM
    if context == "about_kindr":
        system += (
            " The user is on the About page. Emphasize Kindr as a crowdfunding platform for "
            "charitable and community causes, transparency, and trust—without making up specific fees or rules."
        )

    contents = _build_gemini_contents(history, message)
    if not contents:
        return _json_error("Could not build a valid conversation.")

    model = (app_obj.config.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
    reply, err = gemini_generate(api_key, model, system, contents)
    if err:
        _queue_ai_escalation_email(
            app_obj,
            message,
            "gemini_error",
            error_or_model_detail=err,
        )
        return _json_error(err, 502)

    reply, escalated = _strip_escalation_marker(reply)
    if escalated:
        _queue_ai_escalation_email(
            app_obj,
            message,
            "model_could_not_answer",
            ai_reply_excerpt=reply or None,
        )
        if not (reply or "").strip():
            support_em = (app_obj.config.get("SUPPORT_EMAIL") or "bekindrgh@gmail.com").strip()
            reply = (
                "We’ve shared your question with our team. If you’d like to reach us directly, "
                f"email {support_em}."
            )

    return jsonify({"reply": reply})
