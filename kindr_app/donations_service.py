import logging
import secrets
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError

from flask import current_app

from kindr_app.extensions import db
from kindr_app.models import Campaign, Donation
from kindr_app.paystack_client import paystack_verify_transaction

log = logging.getLogger(__name__)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _amount_major_from_paystack(data: dict) -> tuple[float, str]:
    amt = float(data.get("amount") or 0)
    currency = (data.get("currency") or "GHS").upper()
    return amt / 100.0, currency


def apply_successful_charge(reference: str) -> tuple[bool, str]:
    """
    Verify with Paystack and idempotently record a successful payment.
    """
    existing = Donation.query.filter_by(paystack_reference=reference).first()
    if existing and existing.status == "success":
        return True, "already_recorded"

    secret = current_app.config.get("PAYSTACK_SECRET_KEY")
    if not secret:
        return False, "paystack_not_configured"

    verified = paystack_verify_transaction(secret, reference)
    if not verified or not verified.get("status"):
        return False, "verify_failed"

    root = verified.get("data") or {}
    if (root.get("status") or "").lower() != "success":
        return False, "not_successful"

    meta = root.get("metadata") or {}
    raw_cid = meta.get("campaign_id")
    try:
        campaign_id = int(raw_cid)
    except (TypeError, ValueError):
        return False, "missing_campaign"

    campaign = db.session.get(Campaign, campaign_id)
    if not campaign:
        return False, "campaign_not_found"
    if bool(getattr(campaign, "is_closed", False)):
        return False, "campaign_closed"
    end_dt = _as_utc(campaign.end_date)
    if end_dt and end_dt <= datetime.now(timezone.utc):
        campaign.is_closed = True
        if (campaign.status or "") == "accepted":
            campaign.status = "completed"
        db.session.commit()
        return False, "campaign_closed"

    amount_major, currency = _amount_major_from_paystack(root)
    if amount_major <= 0:
        return False, "invalid_amount"

    cust = root.get("customer") or {}
    email = (cust.get("email") or meta.get("payer_email") or "").strip()
    if not email:
        return False, "missing_email"

    first = (cust.get("first_name") or "").strip()
    last = (cust.get("last_name") or "").strip()
    payer_name = (first + " " + last).strip() or None

    donor_uid = meta.get("donor_user_id")
    try:
        donor_user_id = int(donor_uid) if donor_uid is not None and donor_uid != "" else None
    except (TypeError, ValueError):
        donor_user_id = None

    d = Donation(
        campaign_id=campaign_id,
        donor_user_id=donor_user_id,
        amount=amount_major,
        currency=currency,
        payer_email=email.lower(),
        payer_name=payer_name,
        paystack_reference=reference,
        status="success",
    )
    db.session.add(d)
    campaign.raised_amount = (campaign.raised_amount or 0) + amount_major
    campaign.donor_count = (campaign.donor_count or 0) + 1
    if float(campaign.raised_amount or 0) >= float(campaign.goal_amount or 0):
        campaign.is_closed = True
        if (campaign.status or "") == "accepted":
            campaign.status = "completed"
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return True, "already_recorded"
    return True, "recorded"


def new_paystack_reference() -> str:
    return f"KND_{secrets.token_hex(12)}"
