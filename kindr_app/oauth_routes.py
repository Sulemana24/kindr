import secrets

import jwt as pyjwt
import requests
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, redirect, request, session, url_for
from werkzeug.security import generate_password_hash

from kindr_app.extensions import csrf, db
from kindr_app.messaging import send_email_otp
from kindr_app.models import User
from kindr_app.otp_util import create_otp

oauth = OAuth()
bp = Blueprint("oauth", __name__, url_prefix="")


def _apple_client_secret() -> str:
    team = current_app.config["APPLE_TEAM_ID"]
    cid = current_app.config["APPLE_CLIENT_ID"]
    kid = current_app.config["APPLE_KEY_ID"]
    key = (current_app.config["APPLE_PRIVATE_KEY"] or "").replace("\\n", "\n")
    now = int(__import__("time").time())
    payload = {
        "iss": team,
        "iat": now,
        "exp": now + 86400 * 150,
        "aud": "https://appleid.apple.com",
        "sub": cid,
    }
    headers = {"kid": kid, "alg": "ES256"}
    return pyjwt.encode(payload, key, algorithm="ES256", headers=headers)


def init_oauth(app):
    oauth.init_app(app)

    if app.config.get("GOOGLE_CLIENT_ID") and app.config.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=(
                "https://accounts.google.com/.well-known/openid-configuration"
            ),
            client_kwargs={"scope": "openid email profile"},
        )

    if app.config.get("FACEBOOK_CLIENT_ID") and app.config.get(
        "FACEBOOK_CLIENT_SECRET"
    ):
        oauth.register(
            name="facebook",
            client_id=app.config["FACEBOOK_CLIENT_ID"],
            client_secret=app.config["FACEBOOK_CLIENT_SECRET"],
            access_token_url="https://graph.facebook.com/oauth/access_token",
            authorize_url="https://www.facebook.com/dialog/oauth",
            api_base_url="https://graph.facebook.com/v19.0/",
            client_kwargs={"scope": "email public_profile"},
        )

    if all(
        [
            app.config.get("APPLE_CLIENT_ID"),
            app.config.get("APPLE_TEAM_ID"),
            app.config.get("APPLE_KEY_ID"),
            app.config.get("APPLE_PRIVATE_KEY"),
        ]
    ):
        oauth.register(
            name="apple",
            client_id=app.config["APPLE_CLIENT_ID"],
            client_secret=_apple_client_secret,
            authorize_url="https://appleid.apple.com/auth/authorize",
            access_token_url="https://appleid.apple.com/auth/token",
            client_kwargs={
                "scope": "name email",
                "response_mode": "form_post",
            },
        )


_OAUTH_NEXT_ALLOWED = frozenset({"start_campaign"})


def _apply_oauth_next_from_query() -> None:
    """
    Only change session when `next` appears in the query string.
    Visiting /auth/google with no `next` must NOT clear a stored intent
    (e.g. start-campaign flow from another tab or an earlier step).
    """
    if "next" not in request.args:
        return
    nxt = (request.args.get("next") or "").strip()
    if nxt in _OAUTH_NEXT_ALLOWED:
        session["oauth_post_login_next"] = nxt
    else:
        session.pop("oauth_post_login_next", None)


def _finish_social(user: User) -> str:
    if getattr(user, "is_suspended", False):
        return redirect(url_for("main.index", error="account_suspended"))
    code = create_otp(user.id, "oauth_complete")
    ok, err = send_email_otp(current_app, user.email, code, user.name)
    if not ok:
        current_app.logger.error("OAuth OTP email failed: %s", err)
    session["oauth_pending_user_id"] = user.id
    next_slug = session.pop("oauth_post_login_next", None)
    if next_slug in _OAUTH_NEXT_ALLOWED:
        return redirect(url_for("main.index", oauth="pending", next=next_slug))
    return redirect(url_for("main.index", oauth="pending"))


def _random_password_hash() -> str:
    return generate_password_hash(secrets.token_urlsafe(32))


def _google_configured() -> bool:
    return bool(
        current_app.config.get("GOOGLE_CLIENT_ID")
        and current_app.config.get("GOOGLE_CLIENT_SECRET")
    )


def _facebook_configured() -> bool:
    return bool(
        current_app.config.get("FACEBOOK_CLIENT_ID")
        and current_app.config.get("FACEBOOK_CLIENT_SECRET")
    )


def _apple_configured() -> bool:
    return bool(
        current_app.config.get("APPLE_CLIENT_ID")
        and current_app.config.get("APPLE_TEAM_ID")
        and current_app.config.get("APPLE_KEY_ID")
        and current_app.config.get("APPLE_PRIVATE_KEY")
    )


@bp.route("/auth/google")
def google_login():
    if not _google_configured():
        return redirect(url_for("main.index", error="google_oauth_not_configured"))
    _apply_oauth_next_from_query()
    redirect_uri = url_for("oauth.google_callback", _external=True)
    try:
        return oauth.google.authorize_redirect(redirect_uri)
    except Exception:
        current_app.logger.exception("Google authorize redirect failed")
        return redirect(url_for("main.index", error="google_login_failed"))


@bp.route("/auth/google/callback")
def google_callback():
    if not _google_configured():
        return redirect(url_for("main.index", error="google_oauth_not_configured"))
    try:
        token = oauth.google.authorize_access_token()
    except Exception:
        current_app.logger.exception("Google OAuth failed")
        return redirect(url_for("main.index", error="google_login_failed"))

    access = token.get("access_token")
    if not access:
        return redirect(url_for("main.index", error="google_token_missing"))
    try:
        r = requests.get(
            "https://openidconnect.googleapis.com/v1/userinfo",
            headers={"Authorization": f"Bearer {access}"},
            timeout=30,
        )
        r.raise_for_status()
        userinfo = r.json()
    except Exception:
        current_app.logger.exception("Google userinfo failed")
        return redirect(url_for("main.index", error="google_profile_failed"))

    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").lower()
    name = userinfo.get("name") or (email.split("@")[0] if email else "Member")

    if not email or not sub:
        return redirect(url_for("main.index", error="google_email_missing"))

    user = User.query.filter_by(google_sub=sub).first()
    if not user:
        user = User.query.filter_by(email=email).first()
        if user:
            user.google_sub = sub
        else:
            user = User(
                email=email,
                name=name,
                password_hash=_random_password_hash(),
                is_active=True,
                google_sub=sub,
            )
            db.session.add(user)
        db.session.commit()
    else:
        db.session.commit()

    return _finish_social(user)


@bp.route("/auth/facebook")
def facebook_login():
    if not _facebook_configured():
        return redirect(
            url_for("main.index", error="facebook_oauth_not_configured")
        )
    _apply_oauth_next_from_query()
    redirect_uri = url_for("oauth.facebook_callback", _external=True)
    try:
        return oauth.facebook.authorize_redirect(redirect_uri)
    except Exception:
        current_app.logger.exception("Facebook authorize redirect failed")
        return redirect(url_for("main.index", error="facebook_login_failed"))


@bp.route("/auth/facebook/callback")
def facebook_callback():
    if not _facebook_configured():
        return redirect(
            url_for("main.index", error="facebook_oauth_not_configured")
        )
    try:
        token = oauth.facebook.authorize_access_token()
    except Exception:
        current_app.logger.exception("Facebook OAuth failed")
        return redirect(url_for("main.index", error="facebook_login_failed"))

    access = token.get("access_token")
    if not access:
        return redirect(url_for("main.index", error="facebook_token_missing"))

    r = requests.get(
        "https://graph.facebook.com/v19.0/me",
        params={"fields": "id,name,email", "access_token": access},
        timeout=30,
    )
    if r.status_code >= 400:
        return redirect(url_for("main.index", error="facebook_profile_failed"))
    data = r.json()
    fb_id = data.get("id")
    email = (data.get("email") or "").lower()
    name = data.get("name") or "Member"

    if not fb_id:
        return redirect(url_for("main.index", error="facebook_profile_failed"))

    user = User.query.filter_by(facebook_id=fb_id).first()
    if not user and email:
        user = User.query.filter_by(email=email).first()
        if user:
            user.facebook_id = fb_id
            db.session.commit()

    if not user:
        if not email:
            return redirect(
                url_for("main.index", error="facebook_email_required")
            )
        user = User(
            email=email,
            name=name,
            password_hash=_random_password_hash(),
            is_active=True,
            facebook_id=fb_id,
        )
        db.session.add(user)
        db.session.commit()
    else:
        db.session.commit()

    return _finish_social(user)


@bp.route("/auth/apple")
def apple_login():
    if not _apple_configured():
        return redirect(url_for("main.index", error="apple_oauth_not_configured"))
    _apply_oauth_next_from_query()
    redirect_uri = url_for("oauth.apple_callback", _external=True)
    try:
        return oauth.apple.authorize_redirect(redirect_uri)
    except Exception:
        current_app.logger.exception("Apple authorize redirect failed")
        return redirect(url_for("main.index", error="apple_login_failed"))


@csrf.exempt
@bp.route("/auth/apple/callback", methods=["GET", "POST"])
def apple_callback():
    if not _apple_configured():
        return redirect(url_for("main.index", error="apple_oauth_not_configured"))
    try:
        token = oauth.apple.authorize_access_token()
    except Exception:
        current_app.logger.exception("Apple OAuth failed")
        return redirect(url_for("main.index", error="apple_login_failed"))

    id_token = token.get("id_token")
    if not id_token:
        return redirect(url_for("main.index", error="apple_token_missing"))

    try:
        claims = pyjwt.decode(
            id_token,
            options={"verify_signature": False},
            algorithms=["RS256"],
        )
    except Exception:
        return redirect(url_for("main.index", error="apple_token_invalid"))

    sub = claims.get("sub")
    email = (claims.get("email") or "").lower()
    if not sub:
        return redirect(url_for("main.index", error="apple_profile_failed"))

    user = User.query.filter_by(apple_sub=sub).first()
    if not user and email:
        user = User.query.filter_by(email=email).first()
        if user:
            user.apple_sub = sub
            db.session.commit()

    if not user:
        if not email:
            return redirect(
                url_for("main.index", error="apple_email_first_login")
            )
        user = User(
            email=email,
            name=email.split("@")[0],
            password_hash=_random_password_hash(),
            is_active=True,
            apple_sub=sub,
        )
        db.session.add(user)
        db.session.commit()
    else:
        db.session.commit()

    return _finish_social(user)
