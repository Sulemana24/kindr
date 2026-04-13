"""Google Gemini (Generative Language API) — server-side only; key stays off the client."""

from __future__ import annotations

import copy
import logging
from typing import Any

import requests

log = logging.getLogger(__name__)

GEMINI_GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)

_FALLBACK_MODELS = (
    "gemini-2.5-flash",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-2.5-flash-lite",
)


def _sanitize_api_key(key: str) -> str:
    return (key or "").strip().strip("\ufeff").strip()


def _merge_system_into_first_user(
    contents: list[dict[str, Any]], system_instruction: str
) -> list[dict[str, Any]]:
    """If systemInstruction field causes 400 on some setups, fold it into the first user turn."""
    sys = system_instruction.strip()
    if not sys:
        return copy.deepcopy(contents)
    merged = copy.deepcopy(contents)
    prefix = sys + "\n\n---\n\n"
    for block in merged:
        if block.get("role") != "user":
            continue
        parts = block.get("parts") or []
        if parts and isinstance(parts[0], dict):
            parts[0]["text"] = prefix + (parts[0].get("text") or "")
        else:
            block["parts"] = [{"text": prefix.rstrip()}]
        return merged
    merged.insert(0, {"role": "user", "parts": [{"text": prefix.rstrip()}]})
    return merged


def _gemini_generate_once(
    api_key: str,
    model: str,
    system_instruction: str,
    contents: list[dict[str, Any]],
    *,
    timeout: int,
) -> tuple[str | None, str, int]:
    """
    Single HTTP call. Returns (text, error_message, http_status).
    http_status 0 = network error before response.
    """
    if not api_key or not contents:
        return None, "Missing API key or message.", 0

    url = GEMINI_GENERATE_URL.format(model=model)
    payload: dict[str, Any] = {
        "contents": contents,
        "generationConfig": {
            "temperature": 0.65,
            "maxOutputTokens": 1024,
        },
    }
    if system_instruction.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_instruction.strip()}]}

    try:
        r = requests.post(
            url,
            params={"key": api_key},
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        log.warning("Gemini request failed: %s", exc)
        return None, "Could not reach the AI service. Try again in a moment.", 0

    try:
        data = r.json()
    except ValueError:
        return None, (r.text[:300] if r.text else "Invalid response from AI service."), r.status_code

    if r.status_code >= 400:
        err = data.get("error") if isinstance(data.get("error"), dict) else {}
        msg = (err.get("message") or r.text or "Request failed")[:500]
        log.warning("Gemini HTTP %s (%s): %s", r.status_code, model, msg[:240])
        return None, msg, r.status_code

    candidates = data.get("candidates") or []
    if not candidates:
        fb = data.get("promptFeedback") or {}
        block = fb.get("blockReason")
        if block:
            log.warning("Gemini blocked prompt: %s", block)
            return None, "The assistant could not answer that request.", r.status_code
        return None, "No response from the model. Try rephrasing your question.", r.status_code

    cand0 = candidates[0]
    finish = (cand0.get("finishReason") or "").upper()
    if finish and finish not in ("STOP", "MAX_TOKENS", "FINISH_REASON_UNSPECIFIED", ""):
        log.warning("Gemini finishReason=%s model=%s", finish, model)
        if finish in ("SAFETY", "RECITATION", "OTHER"):
            return None, "The assistant could not answer that request.", r.status_code

    parts = (cand0.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        return None, "Empty response from the model.", r.status_code
    return text, "", r.status_code


def _model_chain(primary: str) -> list[str]:
    out: list[str] = []
    for m in (primary,) + _FALLBACK_MODELS:
        m = m.strip()
        if m and m not in out:
            out.append(m)
    return out


def gemini_generate(
    api_key: str,
    model: str,
    system_instruction: str,
    contents: list[dict[str, Any]],
    *,
    timeout: int = 60,
) -> tuple[str | None, str]:
    """
    Try models in order. Per model: call with systemInstruction, then (on 400) with system merged into user text.
    Skip to next model on 404. Stop on 403 (invalid / restricted API key).
    """
    api_key = _sanitize_api_key(api_key)
    if not api_key:
        return None, "API key is missing or empty after trimming."

    last_err = ""
    last_status = 0
    primary = model.strip()

    for m in _model_chain(primary):
        sys_text = system_instruction.strip()

        text, err, status = _gemini_generate_once(
            api_key, m, sys_text, contents, timeout=timeout
        )
        if text is not None:
            if m != primary:
                log.info("Gemini ok with model %s (primary was %r)", m, primary)
            return text, ""

        last_err, last_status = err, status

        if status == 403:
            log.warning("Gemini 403 — check API key and Generative Language API access")
            return None, err

        if status == 404:
            log.info("Gemini model %s not found, trying next", m)
            continue

        if status == 0:
            return None, err

        if status == 400:
            el = err.lower()
            if "api key" in el and ("invalid" in el or "not valid" in el):
                return None, err

        if sys_text and status == 400:
            merged = _merge_system_into_first_user(contents, system_instruction)
            text2, err2, st2 = _gemini_generate_once(
                api_key, m, "", merged, timeout=timeout
            )
            if text2 is not None:
                log.info("Gemini ok with merged system instruction (model %s)", m)
                return text2, ""
            last_err, last_status = err2, st2
            if st2 == 403:
                return None, err2
            if st2 == 404:
                continue

    return None, last_err or "No Gemini model responded successfully."
