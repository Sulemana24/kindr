import logging

from flask import Blueprint, current_app, jsonify, redirect, request, url_for

from kindr_app.donations_service import apply_successful_charge
from kindr_app.extensions import csrf
from kindr_app.paystack_client import paystack_webhook_valid

log = logging.getLogger(__name__)

bp = Blueprint("paystack", __name__)


@bp.route("/paystack/callback")
def paystack_callback():
    ref = request.args.get("reference") or request.args.get("trxref")
    if not ref:
        return redirect(url_for("main.index", donation="missing_ref"))
    ok, msg = apply_successful_charge(ref)
    if ok or msg == "already_recorded":
        return redirect(url_for("main.index", donation="success"))
    log.warning("Paystack callback failed ref=%s msg=%s", ref, msg)
    return redirect(url_for("main.index", donation="failed"))


@csrf.exempt
@bp.route("/paystack/webhook", methods=["POST"])
def paystack_webhook():
    secret = current_app.config.get("PAYSTACK_SECRET_KEY")
    raw = request.get_data()
    sig = request.headers.get("X-Paystack-Signature")
    if not paystack_webhook_valid(secret or "", raw, sig):
        return ("", 400)
    body = request.get_json(silent=True) or {}
    if body.get("event") == "charge.success":
        data = body.get("data") or {}
        ref = data.get("reference")
        if ref:
            ok, msg = apply_successful_charge(ref)
            if not ok and msg not in ("already_recorded",):
                log.warning("Webhook charge record ref=%s msg=%s", ref, msg)
    return jsonify({"ok": True})
