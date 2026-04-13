import logging
import smtplib
from email.message import EmailMessage

import requests

log = logging.getLogger(__name__)


def send_email_otp(app, to_email: str, code: str, name: str) -> tuple[bool, str]:
    subject = "Your Kindr verification code"
    body = (
        f"Hi {name},\n\n"
        f"Your verification code is: {code}\n\n"
        "It expires in 10 minutes. If you did not request this, ignore this email.\n\n"
        "— Kindr"
    )
    host = app.config.get("MAIL_SERVER")
    port = int(app.config.get("MAIL_PORT") or 587)
    user = app.config.get("MAIL_USERNAME")
    password = app.config.get("MAIL_PASSWORD")
    sender = app.config.get("MAIL_DEFAULT_SENDER") or user
    use_tls = app.config.get("MAIL_USE_TLS", True)

    if not host or not sender:
        log.warning("MAIL not configured; OTP email to %s: %s", to_email, code)
        return True, "dev_logged"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.exception("SMTP send failed")
        return False, str(exc)


def send_campaign_status_email(app, to_email: str, name: str, campaign_title: str, status: str) -> tuple[bool, str]:
    status = (status or "").strip().lower()
    if status == "accepted":
        subject = "Your Kindr campaign was accepted"
        body = (
            f"Hi {name},\n\n"
            f"Good news! Your campaign \"{campaign_title}\" has been accepted and is now visible to donors.\n\n"
            "You can sign in to your dashboard to track donations and progress.\n\n"
            "— Kindr"
        )
    elif status == "flagged":
        subject = "Your Kindr campaign needs review"
        body = (
            f"Hi {name},\n\n"
            f"Your campaign \"{campaign_title}\" has been flagged by our admin team and is not currently public.\n\n"
            "Please contact support for next steps.\n\n"
            "— Kindr"
        )
    else:
        subject = "Campaign status updated"
        body = (
            f"Hi {name},\n\n"
            f"Your campaign \"{campaign_title}\" status changed to: {status or 'updated'}.\n\n"
            "— Kindr"
        )

    host = app.config.get("MAIL_SERVER")
    port = int(app.config.get("MAIL_PORT") or 587)
    user = app.config.get("MAIL_USERNAME")
    password = app.config.get("MAIL_PASSWORD")
    sender = app.config.get("MAIL_DEFAULT_SENDER") or user
    use_tls = app.config.get("MAIL_USE_TLS", True)

    if not host or not sender:
        log.warning("MAIL not configured; campaign status email to %s (%s)", to_email, status)
        return True, "dev_logged"
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.exception("Campaign status email failed")
        return False, str(exc)


def send_withdrawal_request_email(
    app,
    *,
    notify_to: str,
    user_name: str,
    user_email: str,
    campaign_title: str,
    campaign_id: int,
    amount: float,
    currency: str,
    requested_at_iso: str,
    admin_dashboard_url: str,
    withdrawal_request_id: int | None = None,
) -> tuple[bool, str]:
    """Notify admins of a new manual withdrawal request (pending review)."""
    notify_to = (notify_to or "").strip()
    if not notify_to:
        log.warning(
            "Withdrawal notify email skipped (no address). User=%s amount=%s",
            user_email,
            amount,
        )
        return True, "no_notify_address"

    wr_part = f"Request ID: {withdrawal_request_id}\n" if withdrawal_request_id else ""
    subject = f"[Kindr] New withdrawal request — {currency} {amount:,.2f}"
    body = (
        f"A fundraiser requested a manual withdrawal.\n\n"
        f"{wr_part}"
        f"User: {user_name}\n"
        f"Email: {user_email}\n"
        f"Campaign: {campaign_title} (ID {campaign_id})\n"
        f"Amount (net): {currency} {amount:,.2f}\n"
        f"Requested at (UTC): {requested_at_iso}\n\n"
        f"Review and mark as completed or rejected in the admin dashboard:\n"
        f"{admin_dashboard_url}\n\n"
        f"— Kindr (automated)"
    )

    host = app.config.get("MAIL_SERVER")
    port = int(app.config.get("MAIL_PORT") or 587)
    user = app.config.get("MAIL_USERNAME")
    password = app.config.get("MAIL_PASSWORD")
    sender = app.config.get("MAIL_DEFAULT_SENDER") or user
    use_tls = app.config.get("MAIL_USE_TLS", True)

    if not host or not sender:
        log.warning("MAIL not configured; withdrawal request email:\n%s", body[:1200])
        return True, "dev_logged"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = notify_to
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.exception("Withdrawal request email failed")
        return False, str(exc)


def send_support_ai_escalation(
    app,
    *,
    support_to: str,
    user_question: str,
    reason: str,
    visitor_email: str | None = None,
    visitor_name: str | None = None,
    error_or_model_detail: str | None = None,
    ai_reply_excerpt: str | None = None,
) -> tuple[bool, str]:
    """
    Notify official support when the AI could not answer (service failure or model escalation).
    Uses the same SMTP settings as OTP when configured; otherwise logs for local dev.
    """
    support_to = (support_to or "").strip()
    if not support_to:
        log.warning("SUPPORT_EMAIL not set; AI escalation not sent. Question: %s", user_question[:200])
        return True, "no_support_email"

    subject = "[Kindr] Assistant could not answer — support follow-up"
    lines = [
        "A visitor used the Kindr AI assistant and needs a human follow-up.",
        "",
        f"Reason: {reason}",
        "",
        "Visitor question:",
        user_question.strip()[:8000],
    ]
    if visitor_email or visitor_name:
        lines.extend(
            [
                "",
                "Signed-in user (if any):",
                f"  Name: {visitor_name or '—'}",
                f"  Email: {visitor_email or '—'}",
            ]
        )
    if error_or_model_detail:
        lines.extend(["", "Technical detail (for staff):", error_or_model_detail.strip()[:2000]])
    if ai_reply_excerpt:
        lines.extend(["", "AI reply excerpt (before escalation):", ai_reply_excerpt.strip()[:2000]])
    lines.extend(["", "— Kindr (automated)"])
    body = "\n".join(lines)

    host = app.config.get("MAIL_SERVER")
    port = int(app.config.get("MAIL_PORT") or 587)
    user = app.config.get("MAIL_USERNAME")
    password = app.config.get("MAIL_PASSWORD")
    sender = app.config.get("MAIL_DEFAULT_SENDER") or user
    use_tls = app.config.get("MAIL_USE_TLS", True)

    if not host or not sender:
        log.warning("MAIL not configured; AI escalation would go to %s:\n%s", support_to, body[:1500])
        return True, "dev_logged"

    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = support_to
        msg.set_content(body)
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            if use_tls:
                smtp.starttls()
            if user and password:
                smtp.login(user, password)
            smtp.send_message(msg)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.exception("Support AI escalation email failed")
        return False, str(exc)


def send_sms_africastalking(app, phone_e164: str, message: str) -> tuple[bool, str]:
    """
    Africa's Talking SMS. Set AT_USERNAME, AT_API_KEY in env.
    phone_e164 example: +233XXXXXXXXX
    """
    username = app.config.get("AT_USERNAME")
    api_key = app.config.get("AT_API_KEY")
    shortcode = app.config.get("AT_SENDER_ID")  # optional alphanumeric sender

    if not username or not api_key:
        log.warning("Africa's Talking not configured; SMS to %s: %s", phone_e164, message)
        return True, "dev_logged"

    url = "https://api.africastalking.com/version1/messaging"
    headers = {"apiKey": api_key, "Content-Type": "application/x-www-form-urlencoded"}
    data = {"username": username, "to": phone_e164, "message": message}
    if shortcode:
        data["from"] = shortcode
    try:
        r = requests.post(url, headers=headers, data=data, timeout=30)
        if r.status_code >= 400:
            return False, r.text or f"HTTP {r.status_code}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        log.exception("Africa's Talking request failed")
        return False, str(exc)


def deliver_otp_code(app, user, code: str, sms_message: str) -> tuple[bool, str, str]:
    """
    Send OTP by email and, when the user has a phone, SMS.
    Succeeds if at least one channel works. Returns (ok, error_detail, user_facing_hint).
    """
    email_ok, email_err = send_email_otp(app, user.email, code, user.name)
    sms_ok = False
    sms_err = ""
    phone = getattr(user, "phone", None)
    if phone:
        sms_ok, sms_err = send_sms_africastalking(app, phone, sms_message)

    if email_ok and sms_ok:
        return True, "", "Enter the verification code sent to your email and phone."
    if email_ok:
        return True, "", "Enter the verification code sent to your email."
    if sms_ok:
        return True, "", "Enter the verification code sent to your phone."
    if phone:
        return (
            False,
            f"Email: {email_err}; SMS: {sms_err}",
            "",
        )
    return False, email_err or "Could not send verification email.", ""
