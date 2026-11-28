"""Pure helpers for the controller's HTTP callback channel (`POST /subscribe`).

No Home Assistant imports, so everything here is unit-tested. The Home
Assistant side - the webhook view, the subscription lifecycle and the watchdog -
is in `push.py`.

Every rule in this module is a measurement from `docs/controller-api.md` §3b,
not a reading of the vendor spec. The two that are easy to get wrong:

* the `X-Callback-Signature` is **base64 of the ASCII hex** of the HMAC, not
  base64 of the 32 raw digest bytes, so a verifier that base64-decodes the
  header and compares a digest never matches; and
* the `Date` header is inside the signed string and is **local time labelled
  `GMT`**, so it is fed back verbatim and is never parsed, re-rendered or used
  as a clock.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from typing import Any
from urllib.parse import urlsplit

# `meta.type` the controller requires in a subscribe body; all three meta fields
# (url, secret, type) are mandatory.
SUBSCRIBE_TYPE = "subscribe.datapoint"

# One callback carries exactly one datapoint, so a generous JSON:API envelope is
# a few hundred bytes. Anything past this is refused unread: the endpoint is
# unauthenticated (the controller cannot speak Home Assistant's auth) and the
# signature can only be checked after the whole body has been buffered.
MAX_CALLBACK_BODY = 65536


def generate_secret() -> str:
    """Return a fresh signing secret for one subscription.

    A new one per config entry and per re-assert. It is never the controller
    password and never anything else Home Assistant holds: the controller keeps
    it in plaintext in its Redis beside the callback URL, so anything with a
    root shell on the controller can read every secret it was ever given.
    """
    return secrets.token_urlsafe(32)


def split_callback_url(url: str) -> tuple[str, str]:
    """Return `(path, authority)` of a callback URL, as the signature needs them."""
    parts = urlsplit(url)
    return (parts.path or "/"), parts.netloc


def signature_message(
    path: str, authority: str, date_header: str, body: bytes
) -> bytes:
    """Return the exact byte string the controller signs.

    `"POST " + url.path + " HTTP/1.1" + url.authority + Date + str(len(body)) + body`,
    concatenated with no separators. Read off the delivery daemon's stripped
    LuaJIT bytecode instruction by instruction and then matched against live
    frames 2 of 2 exactly.

    `path` and `authority` come from the URL that was *registered* with the
    controller, not from the inbound request: the controller builds the string
    from the URL it was given, so a reverse proxy that rewrites `Host` cannot
    invalidate the signature.
    """
    return b"".join(
        (
            b"POST ",
            path.encode("utf-8"),
            b" HTTP/1.1",
            authority.encode("utf-8"),
            date_header.encode("utf-8"),
            str(len(body)).encode("ascii"),
            body,
        )
    )


def expected_signature(
    secret: str, path: str, authority: str, date_header: str, body: bytes
) -> str:
    """Return the `X-Callback-Signature` value a frame should carry.

    base64 of the lowercase hex digest: the controller's `hmacsha256` returns a
    64-character hex string and base64-encodes those characters.
    """
    digest = hmac.new(
        secret.encode("utf-8"),
        signature_message(path, authority, date_header, body),
        hashlib.sha256,
    ).hexdigest()
    return base64.b64encode(digest.encode("ascii")).decode("ascii")


def verify_callback_signature(
    secret: str | None,
    header: str | None,
    path: str,
    authority: str,
    date_header: str | None,
    body: bytes,
) -> bool:
    """Return True when `header` is the signature this body should carry.

    A valid signature proves only that the frame was not tampered with between
    the controller and here. It is not proof of origin - the secret is readable
    on the controller - so it must not authorise anything beyond "this
    datapoint's value is now X".
    """
    if not secret or not header or date_header is None:
        return False
    if len(body) > MAX_CALLBACK_BODY:
        return False
    return hmac.compare_digest(
        header.strip(),
        expected_signature(secret, path, authority, date_header, body),
    )


def subscribe_body(
    datapoint_ids: list[str] | tuple[str, ...], url: str, secret: str
) -> dict[str, Any]:
    """Return the body of a `POST /subscribe` request."""
    return {
        "data": [{"id": dp_id, "type": "datapoint"} for dp_id in datapoint_ids],
        "meta": {"url": url, "secret": secret, "type": SUBSCRIBE_TYPE},
    }


def chunked(ids: list[str], size: int) -> list[list[str]]:
    """Split datapoint ids into subscribe-sized batches (never an empty batch)."""
    if size < 1:
        return [list(ids)] if ids else []
    return [ids[i : i + size] for i in range(0, len(ids), size)]


def parse_callback_body(raw: bytes) -> list[dict[str, Any]]:
    """Return `[{"id", "value", "timestamp"}]` from a callback body.

    JSON:API, one datapoint per POST in every frame measured, but a `data` list
    is accepted as well because the subscribe body is a list and the shape costs
    nothing to allow. `attributes.value` is always a string, in the same
    engineering units as `GET /datapoints` (`dpt.scaling` as a percent, enum
    members by name), which is why nothing here converts it: `datapoints.py`
    decodes both paths unchanged.

    An entry with no id, or with no `value` at all, carries no state and is
    dropped. Anything that is not the expected JSON shape yields an empty list
    rather than raising, because the caller's answer to a bad frame is to ignore
    it.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return []
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    items = data if isinstance(data, list) else [data]
    values: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        dp_id = item.get("id")
        attributes = item.get("attributes")
        if not isinstance(dp_id, str) or not dp_id:
            continue
        if not isinstance(attributes, dict) or "value" not in attributes:
            continue
        values.append(
            {
                "id": dp_id,
                "value": attributes.get("value"),
                "timestamp": attributes.get("timestamp"),
            }
        )
    return values


def subscription_id_from_response(payload: Any) -> str | None:
    """Return the subscription id from a `POST /subscribe` response."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if isinstance(data, list):
        data = next((item for item in data if isinstance(item, dict)), None)
    if not isinstance(data, dict):
        return None
    sub_id = data.get("id")
    return sub_id if isinstance(sub_id, str) and sub_id else None


def callback_path_matches(subscription: Any, path: str) -> bool:
    """Return True when a listed subscription points at our own callback path.

    Reconciliation matches on the **path**, which is derived from the config
    entry id and so is unique to this entry, and deliberately not on the
    authority: the case that leaves an orphan behind is exactly the one where
    Home Assistant's address changed, and an authority match would then miss it.
    Matching on the path also means one entry can never delete another's
    subscription.

    A record whose url this firmware does not report answers False - a
    subscription that cannot be identified is left alone rather than deleted on
    a guess.
    """
    if not isinstance(subscription, dict):
        return False
    meta = subscription.get("meta")
    url = meta.get("url") if isinstance(meta, dict) else None
    if not isinstance(url, str) or not url:
        return False
    try:
        return (urlsplit(url).path or "/") == path
    except ValueError:
        return False


def subscribe_failure_reason(err: BaseException) -> str:
    """Name a failed `POST /subscribe` in one line fit for an entity attribute.

    The exception class alone is what the first real-installation failure
    reported, and it was not enough: `WiserKnxServerError` says the controller
    answered 5xx without saying *which* 5xx, and 500, 503 and 504 point at
    different halves of the controller. The status is therefore included where
    the error carries one.

    The exception's **message** is deliberately left out: it names the
    controller's URL, and an entity attribute is read by anyone who can read
    the state machine and travels into a diagnostics download, which redacts
    the host everywhere else.
    """
    name = type(err).__name__
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return f"{name} (HTTP {status})"
    return name
