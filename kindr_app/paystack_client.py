import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import requests

log = logging.getLogger(__name__)


def paystack_verify_transaction(secret_key: str, reference: str) -> Optional[Dict[str, Any]]:
    if not secret_key or not reference:
        return None
    try:
        r = requests.get(
            f"https://api.paystack.co/transaction/verify/{reference}",
            headers={"Authorization": f"Bearer {secret_key}"},
            timeout=45,
        )
        if r.status_code >= 400:
            log.warning("Paystack verify HTTP %s: %s", r.status_code, r.text[:500])
            return None
        return r.json()
    except Exception:
        log.exception("Paystack verify request failed")
        return None


def paystack_initialize(
    secret_key: str,
    email: str,
    amount_minor: int,
    currency: str,
    reference: str,
    callback_url: str,
    metadata: dict,
) -> Optional[Dict[str, Any]]:
    if not secret_key:
        return None
    payload = {
        "email": email,
        "amount": amount_minor,
        "currency": currency,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata,
    }
    try:
        r = requests.post(
            "https://api.paystack.co/transaction/initialize",
            headers={
                "Authorization": f"Bearer {secret_key}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=45,
        )
        if r.status_code >= 400:
            log.warning("Paystack init HTTP %s: %s", r.status_code, r.text[:500])
            return None
        return r.json()
    except Exception:
        log.exception("Paystack initialize failed")
        return None


def paystack_webhook_valid(secret_key: str, body: bytes, signature_header: str | None) -> bool:
    if not secret_key or not signature_header:
        return False
    digest = hmac.new(
        secret_key.encode("utf-8"),
        body,
        hashlib.sha512,
    ).hexdigest()
    return hmac.compare_digest(digest, signature_header)
