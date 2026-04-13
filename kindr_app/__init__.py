import os
from datetime import timedelta

from flask import Flask, jsonify, request
from flask_wtf.csrf import CSRFError

from kindr_app.extensions import csrf, db, login_manager


def _env_clean(val: str | None) -> str | None:
    """Strip whitespace and optional surrounding quotes from .env values."""
    if val is None:
        return None
    s = val.strip()
    if not s:
        return None
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        inner = s[1:-1].strip()
        return inner or None
    return s


def _database_uri(instance_path: str) -> str:
    """SQLite default, or Postgres from DATABASE_URL (supports Heroku-style postgres://)."""
    raw = _env_clean(os.environ.get("DATABASE_URL"))
    if not raw:
        return "sqlite:///" + os.path.join(instance_path, "kindr.db")
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw


def create_app(test_config=None):
    # Load .env even when the app is started without going through run.py (e.g. flask --app kindr_app:create_app).
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass

    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="static",
        template_folder="templates",
    )
    _cookie_secure = os.environ.get("SESSION_COOKIE_SECURE", "").strip().lower() == "true"
    _cookie_samesite = (os.environ.get("SESSION_COOKIE_SAMESITE") or "Lax").strip() or "Lax"
    if _cookie_samesite not in ("Lax", "Strict", "None"):
        _cookie_samesite = "Lax"
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-only-change-in-production"),
        SQLALCHEMY_DATABASE_URI=_database_uri(app.instance_path),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        # Avoid stale Postgres connections on managed hosts (Render/RDS),
        # which can surface as intermittent SSL EOF errors.
        SQLALCHEMY_ENGINE_OPTIONS={
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "pool_timeout": 30,
        },
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SECURE=_cookie_secure,
        SESSION_COOKIE_SAMESITE=_cookie_samesite,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        WTF_CSRF_TIME_LIMIT=None,
        # When true (and app is in debug), API responses include `dev_otp` to help local testing.
        SHOW_DEV_OTP=os.environ.get("SHOW_DEV_OTP", "").strip().lower() == "true",
        MAIL_SERVER=_env_clean(os.environ.get("MAIL_SERVER")),
        MAIL_PORT=int(os.environ.get("MAIL_PORT") or 587),
        MAIL_USERNAME=_env_clean(os.environ.get("MAIL_USERNAME")),
        MAIL_PASSWORD=_env_clean(os.environ.get("MAIL_PASSWORD")),
        MAIL_DEFAULT_SENDER=_env_clean(os.environ.get("MAIL_DEFAULT_SENDER")),
        MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS", "true").lower() == "true",
        AT_USERNAME=os.environ.get("AT_USERNAME"),
        AT_API_KEY=os.environ.get("AT_API_KEY"),
        AT_SENDER_ID=os.environ.get("AT_SENDER_ID"),
        GOOGLE_CLIENT_ID=os.environ.get("GOOGLE_CLIENT_ID"),
        GOOGLE_CLIENT_SECRET=os.environ.get("GOOGLE_CLIENT_SECRET"),
        FACEBOOK_CLIENT_ID=os.environ.get("FACEBOOK_CLIENT_ID"),
        FACEBOOK_CLIENT_SECRET=os.environ.get("FACEBOOK_CLIENT_SECRET"),
        APPLE_CLIENT_ID=os.environ.get("APPLE_CLIENT_ID"),
        APPLE_TEAM_ID=os.environ.get("APPLE_TEAM_ID"),
        APPLE_KEY_ID=os.environ.get("APPLE_KEY_ID"),
        APPLE_PRIVATE_KEY=os.environ.get("APPLE_PRIVATE_KEY"),
        PAYSTACK_SECRET_KEY=os.environ.get("PAYSTACK_SECRET_KEY", ""),
        PAYSTACK_PUBLIC_KEY=os.environ.get("PAYSTACK_PUBLIC_KEY", ""),
        PAYSTACK_CALLBACK_URL=os.environ.get("PAYSTACK_CALLBACK_URL", ""),
        GEMINI_API_KEY=_env_clean(os.environ.get("GEMINI_API_KEY")),
        GEMINI_MODEL=(os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash").strip()
        or "gemini-2.5-flash",
        SUPPORT_EMAIL=_env_clean(os.environ.get("SUPPORT_EMAIL")) or "bekindrgh@gmail.com",
        WITHDRAWAL_NOTIFY_EMAIL=_env_clean(os.environ.get("WITHDRAWAL_NOTIFY_EMAIL")),
    )

    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(os.path.join(app.static_folder, "uploads", "campaigns"), exist_ok=True)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "main.login"
    csrf.init_app(app)

    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):  # pragma: no cover
        if request.path.startswith("/api/"):
            return jsonify(
                {
                    "message": "Security token expired or missing. Refresh the page and try again.",
                }
            ), 400
        return (
            "<!doctype html><title>400 Bad Request</title>"
            "<p>CSRF validation failed. Refresh the page and try again.</p>",
            400,
            {"Content-Type": "text/html; charset=utf-8"},
        )

    @login_manager.unauthorized_handler
    def _unauthorized():  # pragma: no cover
        from flask import jsonify, redirect, request, url_for

        if request.path.startswith("/api/"):
            return jsonify({"message": "Authentication required."}), 401
        return redirect(url_for("main.index"))

    with app.app_context():
        from kindr_app import models  # noqa: F401

        db.create_all()
        from kindr_app.schema_migrate import run_schema_migrate

        run_schema_migrate(app)
        _seed_demo_data(app)
        _ensure_single_admin_account(app)
        _promote_admin_users(app)

    from kindr_app.api import bp as api_bp

    app.register_blueprint(api_bp, url_prefix="/api")

    from kindr_app.oauth_routes import bp as oauth_bp, init_oauth

    init_oauth(app)
    app.register_blueprint(oauth_bp)

    from kindr_app.paystack_routes import bp as paystack_bp

    app.register_blueprint(paystack_bp)

    from kindr_app.views import bp as main_bp

    app.register_blueprint(main_bp)

    from kindr_app import campaign_utils

    @app.template_global()
    def kindr_category_label(slug):
        return campaign_utils.category_label(slug or "")

    return app


def _promote_admin_users(app) -> None:
    from kindr_app.extensions import db
    from kindr_app.models import User

    # When dedicated single-admin credentials are set, skip email-list promotion.
    if os.environ.get("ADMIN_LOGIN_EMAIL", "").strip() and os.environ.get(
        "ADMIN_LOGIN_PASSWORD", ""
    ).strip():
        return

    raw = os.environ.get("ADMIN_EMAILS", "")
    if not raw.strip():
        return
    for part in raw.split(","):
        email = part.strip().lower()
        if not email:
            continue
        u = User.query.filter_by(email=email).first()
        if u:
            u.is_admin = True
        else:
            app.logger.warning(
                "ADMIN_EMAILS includes %r but no account with that email exists yet. "
                "Sign up with that email first, then restart the app to grant admin.",
                email,
            )
    db.session.commit()


def _ensure_single_admin_account(app) -> None:
    """
    Optional dedicated single-admin account from env.
    If ADMIN_LOGIN_EMAIL and ADMIN_LOGIN_PASSWORD are provided:
    - create/update that account
    - enforce is_admin=True on it
    - enforce is_admin=False on all other users
    """
    from kindr_app.extensions import db
    from kindr_app.models import User

    email = (os.environ.get("ADMIN_LOGIN_EMAIL") or "").strip().lower()
    password = (os.environ.get("ADMIN_LOGIN_PASSWORD") or "").strip()
    name = (os.environ.get("ADMIN_LOGIN_NAME") or "Admin").strip() or "Admin"
    if not email or not password:
        return

    admin_user = User.query.filter_by(email=email).first()
    if not admin_user:
        admin_user = User(
            email=email,
            name=name,
            is_active=True,
            is_admin=True,
        )
        admin_user.set_password(password)
        db.session.add(admin_user)
    else:
        admin_user.name = name
        admin_user.is_active = True
        admin_user.is_admin = True
        admin_user.set_password(password)

    for u in User.query.filter(User.email != email).all():
        if u.is_admin:
            u.is_admin = False

    db.session.commit()


def _seed_demo_data(app) -> None:
    """
    Optional demo data seeding for local development.

    Enable via SEED_DEMO_DATA=true in .env.
    """
    if os.environ.get("SEED_DEMO_DATA", "").strip().lower() != "true":
        return

    from kindr_app.models import Campaign, User

    if Campaign.query.first():
        return

    demo_email = os.environ.get("DEMO_EMAIL", "demo@kindr.local").strip().lower()
    demo_name = os.environ.get("DEMO_NAME", "Demo User").strip() or "Demo User"

    u = User.query.filter_by(email=demo_email).first()
    if not u:
        u = User(email=demo_email, name=demo_name, is_active=True)
        # No password by default; this user is only for demo campaigns display.
        db.session.add(u)
        db.session.commit()

    rows = [
        Campaign(
            user_id=u.id,
            title="Support school supplies for kids",
            category="education",
            goal_amount=5000,
            raised_amount=1200,
            donor_count=18,
            image_url="https://images.unsplash.com/photo-1523240795612-9a054b0db644?w=900&q=80",
            description="Raising funds to provide books, uniforms, and stationery for students in need.",
        ),
        Campaign(
            user_id=u.id,
            title="Community clinic medical support",
            category="health",
            goal_amount=15000,
            raised_amount=4300,
            donor_count=42,
            image_url="https://images.unsplash.com/photo-1584515933487-779824d29309?w=900&q=80",
            description="Help us purchase essential medicines and supplies for a local clinic.",
        ),
    ]
    db.session.add_all(rows)
    db.session.commit()
