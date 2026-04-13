from datetime import datetime, timezone
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from kindr_app.extensions import db, login_manager


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    name = db.Column(db.String(120), nullable=False)
    password_hash = db.Column(db.String(256), nullable=True)
    phone = db.Column(db.String(32), nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    is_suspended = db.Column(db.Boolean, default=False, nullable=False)
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    google_sub = db.Column(db.String(128), nullable=True, unique=True)
    facebook_id = db.Column(db.String(128), nullable=True, unique=True)
    apple_sub = db.Column(db.String(128), nullable=True, unique=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    campaigns = db.relationship("Campaign", backref="owner", lazy="dynamic")
    donations = db.relationship("Donation", backref="donor_user", lazy="dynamic")

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


@login_manager.user_loader
def load_user(user_id):
    user = db.session.get(User, int(user_id))
    if not user:
        return None
    if getattr(user, "is_suspended", False):
        return None
    return user


class OtpChallenge(db.Model):
    __tablename__ = "otp_challenges"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    purpose = db.Column(db.String(40), nullable=False)
    code_hash = db.Column(db.String(256), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    attempts = db.Column(db.Integer, default=0, nullable=False)
    consumed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    user = db.relationship("User", backref=db.backref("otp_challenges", lazy="dynamic"))


class Campaign(db.Model):
    __tablename__ = "campaigns"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    goal_amount = db.Column(db.Float, nullable=False)
    raised_amount = db.Column(db.Float, default=0.0, nullable=False)
    donor_count = db.Column(db.Integer, default=0, nullable=False)
    status = db.Column(db.String(20), default="pending_review", nullable=False)
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    is_closed = db.Column(db.Boolean, default=False, nullable=False)
    withdrawal_requested_at = db.Column(db.DateTime, nullable=True)
    withdrawal_fee_amount = db.Column(db.Float, default=0.0, nullable=False)
    withdrawal_net_amount = db.Column(db.Float, default=0.0, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    description = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    donations = db.relationship(
        "Donation",
        backref="campaign",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )


class Donation(db.Model):
    __tablename__ = "donations"

    id = db.Column(db.Integer, primary_key=True)
    campaign_id = db.Column(
        db.Integer, db.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    donor_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default="GHS", nullable=False)
    payer_email = db.Column(db.String(255), nullable=False)
    payer_name = db.Column(db.String(120), nullable=True)
    paystack_reference = db.Column(db.String(120), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), default="pending", nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class BlogPost(db.Model):
    __tablename__ = "blog_posts"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    title = db.Column(db.String(220), nullable=False)
    post_type = db.Column(db.String(30), nullable=False, default="story")
    content = db.Column(db.Text, nullable=False)
    image_url = db.Column(db.String(500), nullable=True)
    price = db.Column(db.Float, nullable=True)
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    author = db.relationship("User", backref=db.backref("blog_posts", lazy="dynamic"))


class WithdrawalRequest(db.Model):
    """Manual payout queue: user requests; admin completes or rejects outside Paystack."""

    __tablename__ = "withdrawal_requests"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    campaign_id = db.Column(db.Integer, db.ForeignKey("campaigns.id"), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(10), default="GHS", nullable=False)
    status = db.Column(db.String(20), default="pending", nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    rejected_at = db.Column(db.DateTime, nullable=True)
    rejection_note = db.Column(db.Text, nullable=True)

    payout_reference = db.Column(db.String(200), nullable=True)
    payout_amount = db.Column(db.Float, nullable=True)
    payout_completed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], backref=db.backref("withdrawal_requests", lazy="dynamic"))
    campaign = db.relationship("Campaign", backref=db.backref("withdrawal_requests", lazy="dynamic"))
    reviewed_by = db.relationship("User", foreign_keys=[reviewed_by_user_id])
