import csv
import io
from datetime import datetime, timedelta, timezone

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    make_response,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, logout_user
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from kindr_app.extensions import db
from kindr_app.messaging import send_campaign_status_email, send_withdrawal_request_email
from kindr_app.models import BlogPost, Campaign, Donation, User, WithdrawalRequest

bp = Blueprint("main", __name__)
WITHDRAW_FEE_RATE = 0.07

# Lowercase emails that may test the manual withdrawal flow without meeting goal/end-date rules.
# Remove or edit in production when no longer needed.
DEMO_WITHDRAW_EMAILS = frozenset({"wuroakondo@gmail.com"})


def _withdraw_demo_user(user) -> bool:
    em = (getattr(user, "email", None) or "").strip().lower()
    return em in DEMO_WITHDRAW_EMAILS


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _campaign_is_ended(c: Campaign) -> bool:
    now = datetime.now(timezone.utc)
    end_dt = _as_utc(c.end_date)
    if end_dt and end_dt <= now:
        return True
    return float(c.raised_amount or 0) >= float(c.goal_amount or 0)


def _close_campaign_if_due(c: Campaign) -> bool:
    if bool(getattr(c, "is_closed", False)):
        return False
    if not _campaign_is_ended(c):
        return False
    c.is_closed = True
    if (c.status or "") == "accepted":
        c.status = "completed"
    return True

_SECONDARY = {
    "about": (
        "About Kindr",
        """<p>
        Kindr is a digital crowdfunding platform built to make fundraising
        simple, transparent, and accessible for everyone. We help individuals,
        communities, churches, and organizations raise funds for important
        needs—whether it’s healthcare, education, or local projects. In many
        communities, fundraising still relies on informal methods that can be
        stressful, limited in reach, and difficult to track. Kindr changes that
        by providing a secure platform where campaigns can be created, shared
        widely, and supported with ease. We are committed to building trust
        through transparency, ensuring that every donation is accounted for and
        every campaign is easy to follow. By combining technology with
        community, Kindr makes it possible for more people to get the support
        they need, when they need it most.
        </p>""",
        "About — Kindr",
    ),
    "faq": (
        "Donor FAQ",
        "<p>Find answers to common questions about donating and supporting campaigns.</p>",
        "FAQ — Kindr",
    ),
    "help": (
        "Help Center",
        "<p>Need help? Browse guides or contact support.</p>",
        "Help — Kindr",
    ),
    "trust": (
        "Trust & Safety",
        "<p>We ensure all campaigns are reviewed and donors are protected.</p>",
        "Trust — Kindr",
    ),
    "privacy": (
        "Privacy Policy",
        "<p>Your data is kept secure and will never be sold. We respect your privacy.</p>",
        "Privacy — Kindr",
    ),
    "pricing": (
        "Pricing",
        """<p>
        Kindr charges a 7% platform fee to keep our service running smoothly and
        securely. This covers payment processing, platform maintenance, and
        continuous improvements to ensure a transparent and reliable fundraising
        experience.
        </p>""",
        "Pricing — Kindr",
    ),
    "terms": (
        "Terms of Service",
        "<p>By using Kindr, you agree to follow our platform rules and guidelines.</p>",
        "Terms — Kindr",
    ),
    "contact": (
        "Contact Us",
        "<p>Email: bekindrgh@gmail.com</p><p>Phone: +233 595 403 340</p>",
        "Contact — Kindr",
    ),
    "careers": (
        "Careers",
        "<p>Join our mission to make giving easier and more impactful.</p>",
        "Careers — Kindr",
    ),
}


@bp.route("/")
def index():
    r = make_response(render_template("index.html"))
    r.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    r.headers["Pragma"] = "no-cache"
    return r


@bp.route("/start-campaign")
def start_campaign():
    """Entry point for Start campaign: requires login, then opens campaign flow on home."""
    if not current_user.is_authenticated:
        return redirect(url_for("main.index", login="1", next="start_campaign"))
    return redirect(url_for("main.index", open_campaign="1"))


@bp.route("/login")
def login():
    # Render the home page but force the sign-in modal open via query flag.
    return redirect(url_for("main.index", login="1"))


@bp.get("/logout")
def server_logout():
    """End the session and redirect home (navigation-based; no CSRF / fetch required)."""
    logout_user()
    session.clear()
    resp = redirect(url_for("main.index", _="logout"))
    resp.delete_cookie(current_app.config.get("SESSION_COOKIE_NAME", "session"))
    resp.delete_cookie("remember_token")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, private"
    resp.headers["Pragma"] = "no-cache"
    return resp


@bp.route("/dashboard")
@login_required
def dashboard():
    rows = (
        Campaign.query.filter_by(user_id=current_user.id)
        .order_by(Campaign.created_at.desc())
        .all()
    )
    changed = False
    for c in rows:
        if _close_campaign_if_due(c):
            changed = True
    if changed:
        db.session.commit()
    total_campaigns = len(rows)
    total_raised = float(sum((c.raised_amount or 0) for c in rows))
    # Until a dedicated page-view tracker is added, use donor engagement as views signal.
    total_views = int(sum((c.donor_count or 0) for c in rows))
    withdraw_status = (request.args.get("withdraw") or "").strip().lower()
    wr_by_campaign: dict[int, WithdrawalRequest] = {}
    if rows:
        ids = [c.id for c in rows]
        wr_rows = (
            WithdrawalRequest.query.filter(WithdrawalRequest.campaign_id.in_(ids))
            .order_by(WithdrawalRequest.requested_at.desc())
            .all()
        )
        for wr in wr_rows:
            if wr.campaign_id not in wr_by_campaign:
                wr_by_campaign[wr.campaign_id] = wr
    return render_template(
        "dashboard.html",
        campaigns=rows,
        total_campaigns=total_campaigns,
        total_raised=total_raised,
        total_views=total_views,
        withdraw_status=withdraw_status,
        withdraw_fee_percent=int(WITHDRAW_FEE_RATE * 100),
        now_utc=datetime.now(timezone.utc),
        now_naive=datetime.utcnow(),
        wr_by_campaign=wr_by_campaign,
        withdraw_demo_bypass=_withdraw_demo_user(current_user),
    )


@bp.get("/dashboard/export")
@login_required
def dashboard_export():
    rows = (
        Campaign.query.filter_by(user_id=current_user.id)
        .order_by(Campaign.created_at.desc())
        .all()
    )
    sio = io.StringIO()
    w = csv.writer(sio)
    w.writerow(
        [
            "Title",
            "Category",
            "Goal",
            "Raised",
            "Donors",
            "Status",
            "Created",
            "Completion",
            "Closed",
            "Withdrawal Requested",
            "Withdrawal Fee (7%)",
            "Withdrawal Net",
        ]
    )
    for c in rows:
        w.writerow(
            [
                c.title,
                c.category,
                float(c.goal_amount or 0),
                float(c.raised_amount or 0),
                int(c.donor_count or 0),
                c.status or "pending_review",
                c.start_date.strftime("%Y-%m-%d") if c.start_date else "",
                c.end_date.strftime("%Y-%m-%d") if c.end_date else "",
                "yes" if c.is_closed else "no",
                c.withdrawal_requested_at.strftime("%Y-%m-%d %H:%M:%S")
                if c.withdrawal_requested_at
                else "",
                float(c.withdrawal_fee_amount or 0),
                float(c.withdrawal_net_amount or 0),
            ]
        )
    filename = f"kindr_campaigns_{current_user.id}.csv"
    return Response(
        sio.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@bp.post("/dashboard/withdraw/<int:campaign_id>")
@login_required
def dashboard_withdraw(campaign_id):
    c = Campaign.query.filter_by(id=campaign_id, user_id=current_user.id).first()
    if not c:
        return redirect(url_for("main.dashboard", withdraw="not_found"))
    if _close_campaign_if_due(c):
        db.session.commit()
    existing = (
        WithdrawalRequest.query.filter_by(campaign_id=c.id)
        .filter(WithdrawalRequest.status.in_(("pending", "completed")))
        .first()
    )
    if existing:
        return redirect(url_for("main.dashboard", withdraw="already_requested"))
    demo = _withdraw_demo_user(current_user)
    eligible = _campaign_is_ended(c)
    if not eligible and not demo:
        return redirect(url_for("main.dashboard", withdraw="not_eligible"))
    total_raised = float(c.raised_amount or 0)
    if demo and not eligible:
        total_raised = max(total_raised, 100.0)
    fee_amount = round(total_raised * WITHDRAW_FEE_RATE, 2)
    estimated_available = round(total_raised - fee_amount, 2)
    if estimated_available <= 0:
        if not demo:
            return redirect(url_for("main.dashboard", withdraw="none"))
        total_raised = 100.0
        fee_amount = round(total_raised * WITHDRAW_FEE_RATE, 2)
        estimated_available = round(total_raised - fee_amount, 2)
    if demo and not _campaign_is_ended(c):
        current_app.logger.info(
            "Demo withdrawal: user=%s campaign_id=%s using synthetic gross=%.2f net=%.2f",
            current_user.email,
            c.id,
            total_raised,
            estimated_available,
        )
    now = datetime.now(timezone.utc)
    c.withdrawal_requested_at = now
    c.withdrawal_fee_amount = fee_amount
    c.withdrawal_net_amount = estimated_available
    c.is_closed = True
    if (c.status or "") == "accepted":
        c.status = "completed"

    wr = WithdrawalRequest(
        user_id=current_user.id,
        campaign_id=c.id,
        amount=estimated_available,
        currency="GHS",
        status="pending",
        requested_at=now,
    )
    db.session.add(wr)
    db.session.commit()

    admin_url = url_for("main.admin_dashboard", _external=True) + "#withdrawals"
    notify_to = (current_app.config.get("WITHDRAWAL_NOTIFY_EMAIL") or "").strip() or (
        current_app.config.get("SUPPORT_EMAIL") or ""
    ).strip()
    send_withdrawal_request_email(
        current_app,
        notify_to=notify_to,
        user_name=current_user.name or "—",
        user_email=current_user.email or "—",
        campaign_title=c.title or "—",
        campaign_id=c.id,
        amount=float(estimated_available),
        currency="GHS",
        requested_at_iso=now.strftime("%Y-%m-%d %H:%M:%S UTC"),
        admin_dashboard_url=admin_url,
        withdrawal_request_id=wr.id,
    )
    current_app.logger.info(
        "Withdrawal request id=%s user_id=%s email=%s campaign_id=%s gross=%.2f fee=%.2f net=%.2f",
        wr.id,
        current_user.id,
        current_user.email,
        c.id,
        total_raised,
        fee_amount,
        estimated_available,
    )
    return redirect(url_for("main.dashboard", withdraw="requested"))


@bp.get("/blog")
def blog():
    post_type_filter = (request.args.get("type") or "").strip().lower()
    q = BlogPost.query.filter_by(is_published=True)
    if post_type_filter in ("story", "news", "marketplace"):
        q = q.filter_by(post_type=post_type_filter)
    rows = q.order_by(BlogPost.created_at.desc()).limit(200).all()
    post_status = (request.args.get("post") or "").strip().lower()
    blog_filter = post_type_filter if post_type_filter in ("story", "news", "marketplace") else "all"
    return render_template(
        "blog.html",
        posts=rows,
        post_status=post_status,
        blog_filter=blog_filter,
    )


@bp.get("/blog/<int:post_id>")
def blog_post(post_id):
    p = BlogPost.query.filter_by(id=post_id, is_published=True).first()
    if not p:
        abort(404)
    return render_template("blog_post.html", post=p, blog_filter="all")


@bp.post("/blog/create")
@login_required
def blog_create():
    title = (request.form.get("title") or "").strip()
    post_type = (request.form.get("post_type") or "story").strip().lower()
    content = (request.form.get("content") or "").strip()
    image_url = (request.form.get("image_url") or "").strip() or None
    price_raw = (request.form.get("price") or "").strip()
    if not title or not content:
        return redirect(url_for("main.blog", post="missing"))
    allowed_types = {"story", "news", "marketplace"}
    if post_type not in allowed_types:
        post_type = "story"
    price = None
    if post_type == "marketplace" and price_raw:
        try:
            price = float(price_raw)
        except ValueError:
            return redirect(url_for("main.blog", post="bad_price"))
        if price < 0:
            return redirect(url_for("main.blog", post="bad_price"))
    p = BlogPost(
        user_id=current_user.id,
        title=title,
        post_type=post_type,
        content=content,
        image_url=image_url,
        price=price,
        is_published=True,
    )
    db.session.add(p)
    db.session.commit()
    return redirect(url_for("main.blog", post="created"))


@bp.route("/admin")
@login_required
def admin_dashboard():
    if not getattr(current_user, "is_admin", False):
        abort(403)
    campaigns = Campaign.query.order_by(Campaign.created_at.desc()).all()
    donations = Donation.query.order_by(Donation.created_at.desc()).limit(300).all()
    users = User.query.order_by(User.created_at.desc()).limit(500).all()

    total_campaigns = Campaign.query.count()
    active_campaigns = Campaign.query.filter_by(status="accepted").count()
    completed_campaigns = Campaign.query.filter(
        Campaign.status == "accepted", Campaign.raised_amount >= Campaign.goal_amount
    ).count()
    total_users = User.query.count()
    total_donors = (
        db.session.query(func.count(func.distinct(Donation.payer_email)))
        .filter(Donation.status == "success")
        .scalar()
        or 0
    )
    total_raised = float(
        db.session.query(func.coalesce(func.sum(Campaign.raised_amount), 0)).scalar() or 0
    )
    successful_payments = Donation.query.filter_by(status="success").count()
    pending_payments = Donation.query.filter_by(status="pending").count()
    failed_payments = Donation.query.filter_by(status="failed").count()
    total_payouts = round(total_raised * 0.93, 2)
    pending_withdrawals = float(
        db.session.query(func.coalesce(func.sum(WithdrawalRequest.amount), 0))
        .filter(WithdrawalRequest.status == "pending")
        .scalar()
        or 0
    )
    manual_payouts_completed = float(
        db.session.query(func.coalesce(func.sum(WithdrawalRequest.payout_amount), 0))
        .filter(WithdrawalRequest.status == "completed")
        .scalar()
        or 0
    )
    avg_donation = round(
        float(
            db.session.query(func.coalesce(func.avg(Donation.amount), 0))
            .filter(Donation.status == "success")
            .scalar()
            or 0
        ),
        2,
    )
    platform_revenue = round(total_raised * 0.07, 2)

    verified_users = User.query.filter_by(is_active=True).count()
    unverified_users = User.query.filter_by(is_active=False).count()
    suspended_users = User.query.filter_by(is_suspended=True).count()
    repeat_donors = (
        db.session.query(Donation.payer_email)
        .filter(Donation.status == "success")
        .group_by(Donation.payer_email)
        .having(func.count(Donation.id) > 1)
        .count()
    )

    approved_campaigns = Campaign.query.filter_by(status="accepted").count()
    rejected_campaigns = Campaign.query.filter_by(status="rejected").count()
    flagged_campaigns = Campaign.query.filter_by(status="flagged").count()
    removed_campaigns = 0
    pending_campaigns = Campaign.query.filter_by(status="pending_review").count()
    success_rate = round((completed_campaigns / total_campaigns) * 100, 1) if total_campaigns else 0
    trending_campaigns = (
        Campaign.query.order_by(Campaign.donor_count.desc(), Campaign.raised_amount.desc())
        .limit(5)
        .all()
    )
    nearing_goal_campaigns = Campaign.query.filter(
        Campaign.status == "accepted",
        Campaign.goal_amount > 0,
        (Campaign.raised_amount / Campaign.goal_amount) >= 0.8,
    ).count()

    recent_transactions = (
        Donation.query.order_by(Donation.created_at.desc())
        .limit(12)
        .all()
    )
    refund_requests = 0
    chargebacks_disputes = 0

    top_donors = (
        db.session.query(
            Donation.payer_email.label("email"),
            func.coalesce(func.sum(Donation.amount), 0).label("amount"),
            func.count(Donation.id).label("count"),
        )
        .filter(Donation.status == "success")
        .group_by(Donation.payer_email)
        .order_by(func.sum(Donation.amount).desc())
        .limit(10)
        .all()
    )

    now = datetime.now(timezone.utc)
    revenue_points = []
    growth_points = []
    campaign_perf_points = []
    for i in range(6, -1, -1):
        day = (now - timedelta(days=i)).date()
        day_start = datetime.combine(day, datetime.min.time(), tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        rev = (
            db.session.query(func.coalesce(func.sum(Donation.amount), 0))
            .filter(Donation.status == "success")
            .filter(Donation.created_at >= day_start, Donation.created_at < day_end)
            .scalar()
            or 0
        )
        ucount = (
            db.session.query(func.count(User.id))
            .filter(User.created_at >= day_start, User.created_at < day_end)
            .scalar()
            or 0
        )
        ccount = (
            db.session.query(func.count(Campaign.id))
            .filter(Campaign.created_at >= day_start, Campaign.created_at < day_end)
            .scalar()
            or 0
        )
        revenue_points.append({"label": day.strftime("%d %b"), "value": float(rev)})
        growth_points.append({"label": day.strftime("%d %b"), "value": int(ucount)})
        campaign_perf_points.append({"label": day.strftime("%d %b"), "value": int(ccount)})

    donor_distribution = {
        "one_time": max(0, int(total_donors - repeat_donors)),
        "repeat": int(repeat_donors),
    }
    conversion_rate = round(
        (successful_payments / max(total_users * 3, 1)) * 100,
        2,
    )

    stats = {
        "campaigns_count": total_campaigns,
        "users_count": total_users,
        "donations_count": Donation.query.count(),
        "pending_payments_count": pending_payments,
        "flagged_campaigns_count": flagged_campaigns,
        "accepted_campaigns_count": approved_campaigns,
        "pending_campaigns_count": pending_campaigns,
        "total_raised": total_raised,
    }

    executive = {
        "total_campaigns": total_campaigns,
        "active_campaigns": active_campaigns,
        "completed_campaigns": completed_campaigns,
        "total_users": total_users,
        "total_donors": int(total_donors),
        "total_raised": total_raised,
        "avg_donation": avg_donation,
        "platform_revenue": platform_revenue,
    }
    financial = {
        "successful_payments": successful_payments,
        "pending_payments": pending_payments,
        "failed_payments": failed_payments,
        "total_payouts": total_payouts,
        "pending_withdrawals": pending_withdrawals,
        "manual_payouts_completed": manual_payouts_completed,
        "refund_requests": refund_requests,
        "chargebacks_disputes": chargebacks_disputes,
    }
    user_stats = {
        "total_users": total_users,
        "verified_users": verified_users,
        "unverified_users": unverified_users,
        "suspended_users": suspended_users,
        "repeat_donors": repeat_donors,
    }
    campaign_stats = {
        "pending_approval": pending_campaigns,
        "approved": approved_campaigns,
        "rejected": rejected_campaigns,
        "flagged": flagged_campaigns,
        "removed": removed_campaigns,
        "trending_count": len(trending_campaigns),
        "nearing_goal": nearing_goal_campaigns,
        "success_rate": success_rate,
    }
    alerts = [
        {"level": "high", "text": f"{failed_payments} failed payments detected in monitoring window."},
        {"level": "medium", "text": f"{flagged_campaigns} campaigns currently flagged by admins."},
        {"level": "low", "text": f"{pending_payments} transactions are still pending settlement."},
    ]
    system_controls = {
        "platform_fee": 7,
        "gateway": "Paystack",
        "email_otp_enabled": True,
    }

    withdrawal_requests = (
        WithdrawalRequest.query.options(
            joinedload(WithdrawalRequest.user),
            joinedload(WithdrawalRequest.campaign),
            joinedload(WithdrawalRequest.reviewed_by),
        )
        .order_by(WithdrawalRequest.requested_at.desc())
        .limit(200)
        .all()
    )

    return render_template(
        "admin_dashboard.html",
        campaigns=campaigns,
        donations=donations,
        users=users,
        withdrawal_requests=withdrawal_requests,
        stats=stats,
        executive=executive,
        financial=financial,
        user_stats=user_stats,
        campaign_stats=campaign_stats,
        top_donors=top_donors,
        recent_transactions=recent_transactions,
        revenue_points=revenue_points,
        growth_points=growth_points,
        campaign_perf_points=campaign_perf_points,
        donor_distribution=donor_distribution,
        conversion_rate=conversion_rate,
        alerts=alerts,
        system_controls=system_controls,
    )


@bp.post("/admin/campaigns/<int:campaign_id>/delete")
@login_required
def admin_delete_campaign(campaign_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    c = db.session.get(Campaign, campaign_id)
    if c:
        db.session.delete(c)
        db.session.commit()
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/campaigns/<int:campaign_id>/accept")
@login_required
def admin_accept_campaign(campaign_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    c = db.session.get(Campaign, campaign_id)
    if c:
        c.status = "accepted"
        db.session.commit()
        if c.owner and c.owner.email:
            send_campaign_status_email(
                current_app,
                c.owner.email,
                c.owner.name,
                c.title,
                "accepted",
            )
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/campaigns/<int:campaign_id>/flag")
@login_required
def admin_flag_campaign(campaign_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    c = db.session.get(Campaign, campaign_id)
    if c:
        c.status = "flagged"
        db.session.commit()
        if c.owner and c.owner.email:
            send_campaign_status_email(
                current_app,
                c.owner.email,
                c.owner.name,
                c.title,
                "flagged",
            )
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/campaigns/<int:campaign_id>/reject")
@login_required
def admin_reject_campaign(campaign_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    c = db.session.get(Campaign, campaign_id)
    if c:
        c.status = "rejected"
        db.session.commit()
        if c.owner and c.owner.email:
            send_campaign_status_email(
                current_app,
                c.owner.email,
                c.owner.name,
                c.title,
                "flagged",
            )
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/users/<int:user_id>/verify")
@login_required
def admin_verify_user(user_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    u = db.session.get(User, user_id)
    if u:
        u.is_active = True
        db.session.commit()
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/users/<int:user_id>/toggle-suspend")
@login_required
def admin_toggle_suspend_user(user_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    u = db.session.get(User, user_id)
    if u:
        u.is_suspended = not bool(getattr(u, "is_suspended", False))
        db.session.commit()
    return redirect(url_for("main.admin_dashboard"))


@bp.post("/admin/withdrawals/<int:request_id>/complete")
@login_required
def admin_complete_withdrawal(request_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    wr = db.session.get(WithdrawalRequest, request_id)
    if not wr or (wr.status or "") != "pending":
        return redirect(url_for("main.admin_dashboard", w="bad_state") + "#withdrawals")
    ref = (request.form.get("payout_reference") or "").strip()
    if not ref:
        return redirect(url_for("main.admin_dashboard", w="missing_ref") + "#withdrawals")
    amt_raw = (request.form.get("payout_amount") or "").strip()
    try:
        payout_amt = float(amt_raw) if amt_raw else float(wr.amount or 0)
    except ValueError:
        return redirect(url_for("main.admin_dashboard", w="bad_amount") + "#withdrawals")
    if payout_amt <= 0:
        return redirect(url_for("main.admin_dashboard", w="bad_amount") + "#withdrawals")
    now = datetime.now(timezone.utc)
    wr.status = "completed"
    wr.payout_reference = ref
    wr.payout_amount = round(payout_amt, 2)
    wr.payout_completed_at = now
    wr.reviewed_by_user_id = current_user.id
    wr.rejected_at = None
    wr.rejection_note = None
    db.session.commit()
    return redirect(url_for("main.admin_dashboard", w="completed") + "#withdrawals")


@bp.post("/admin/withdrawals/<int:request_id>/reject")
@login_required
def admin_reject_withdrawal(request_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    wr = db.session.get(WithdrawalRequest, request_id)
    if not wr or (wr.status or "") != "pending":
        return redirect(url_for("main.admin_dashboard", w="bad_state") + "#withdrawals")
    note = (request.form.get("rejection_note") or "").strip() or None
    now = datetime.now(timezone.utc)
    wr.status = "rejected"
    wr.rejected_at = now
    wr.rejection_note = note
    wr.reviewed_by_user_id = current_user.id
    camp = wr.campaign
    if camp:
        camp.withdrawal_requested_at = None
        camp.withdrawal_fee_amount = 0.0
        camp.withdrawal_net_amount = 0.0
    db.session.commit()
    return redirect(url_for("main.admin_dashboard", w="rejected") + "#withdrawals")


@bp.route("/admin/users/<int:user_id>/donations")
@login_required
def admin_user_donations(user_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    u = db.session.get(User, user_id)
    if not u:
        abort(404)
    rows = (
        Donation.query.filter(
            (Donation.donor_user_id == user_id) | (Donation.payer_email == u.email)
        )
        .order_by(Donation.created_at.desc())
        .all()
    )
    return render_template("admin_user_donations.html", target_user=u, donations=rows)


@bp.post("/admin/donations/<int:donation_id>/delete")
@login_required
def admin_delete_donation(donation_id):
    if not getattr(current_user, "is_admin", False):
        abort(403)
    d = db.session.get(Donation, donation_id)
    if d:
        c = db.session.get(Campaign, d.campaign_id)
        if c and (d.status or "").lower() == "success":
            c.raised_amount = max(0.0, (c.raised_amount or 0.0) - float(d.amount or 0.0))
            c.donor_count = max(0, int(c.donor_count or 0) - 1)
        db.session.delete(d)
        db.session.commit()
    return redirect(url_for("main.admin_dashboard"))


def _secondary(slug: str):
    if slug not in _SECONDARY:
        abort(404)
    h1, body, title = _SECONDARY[slug]
    return render_template("secondary.html", page_h1=h1, page_body=body, page_title=title)


@bp.route("/about")
def about():
    return render_template("about.html", page_title="About — Kindr")


@bp.route("/faq")
def faq():
    return _secondary("faq")


@bp.route("/help")
def help_page():
    return _secondary("help")


@bp.route("/trust")
def trust():
    return _secondary("trust")


@bp.route("/privacy")
def privacy():
    return _secondary("privacy")


@bp.route("/pricing")
def pricing():
    return _secondary("pricing")


@bp.route("/terms")
def terms():
    return _secondary("terms")


@bp.route("/contact")
def contact():
    return _secondary("contact")


@bp.route("/careers")
def careers():
    return _secondary("careers")
