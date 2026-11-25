"""The pure half of push: the callback signature, the frame and the subscribe body.

Every expectation in here is a measurement from `docs/controller-api.md` §3b.
The signature construction in particular was read off the controller's delivery
daemon bytecode and matched against live frames, so these tests pin the exact
byte string and the exact encoding rather than a re-derivation of them.
"""

import base64
import hashlib
import hmac
import json

import pytest

from custom_components.wiser_for_knx.push_utils import (
    MAX_CALLBACK_BODY,
    SUBSCRIBE_TYPE,
    callback_path_matches,
    chunked,
    expected_signature,
    generate_secret,
    parse_callback_body,
    signature_message,
    split_callback_url,
    subscribe_body,
    subscription_id_from_response,
    verify_callback_signature,
)

SECRET = "s3cret-not-a-real-one"
URL = "http://192.168.1.x:8123/api/webhook/abc123"
PATH = "/api/webhook/abc123"
AUTHORITY = "192.168.1.x:8123"
# Local time labelled GMT, exactly as the controller sends it: it is inside the
# signed string, so it is fed back verbatim and never parsed.
DATE = "Sun, 22 Nov 2026 19:04:11 GMT"
BODY = (
    b'{"data":{"id":"dp-1","type":"datapoint",'
    b'"attributes":{"value":"20","timestamp":"2026-11-22T18:04:11Z"}}}'
)


def test_signed_message_is_the_measured_concatenation():
    """No separators: "POST " + path + " HTTP/1.1" + authority + Date + len + body."""
    assert signature_message(PATH, AUTHORITY, DATE, BODY) == (
        b"POST "
        + PATH.encode()
        + b" HTTP/1.1"
        + AUTHORITY.encode()
        + DATE.encode()
        + str(len(BODY)).encode()
        + BODY
    )


def test_signature_is_base64_of_the_ascii_hex():
    """base64 of the 64 hex characters, not of the 32 raw digest bytes."""
    digest = hmac.new(
        SECRET.encode(), signature_message(PATH, AUTHORITY, DATE, BODY), hashlib.sha256
    )
    signature = expected_signature(SECRET, PATH, AUTHORITY, DATE, BODY)
    assert signature == base64.b64encode(digest.hexdigest().encode("ascii")).decode()
    # The trap: the raw-digest encoding is a different string, and a verifier
    # that base64-decodes the header to compare 32 bytes never matches.
    assert signature != base64.b64encode(digest.digest()).decode()
    assert len(base64.b64decode(signature)) == 64


def test_signature_hex_is_lowercase():
    signature = expected_signature(SECRET, PATH, AUTHORITY, DATE, BODY)
    decoded = base64.b64decode(signature).decode("ascii")
    assert decoded == decoded.lower()


def test_verify_accepts_a_correctly_signed_frame():
    header = expected_signature(SECRET, PATH, AUTHORITY, DATE, BODY)
    assert verify_callback_signature(SECRET, header, PATH, AUTHORITY, DATE, BODY)
    # Surrounding whitespace from the header round trip is not a mismatch
    assert verify_callback_signature(SECRET, f" {header} ", PATH, AUTHORITY, DATE, BODY)


@pytest.mark.parametrize(
    ("secret", "path", "authority", "date", "body"),
    [
        ("another-secret", PATH, AUTHORITY, DATE, BODY),
        (SECRET, "/api/webhook/other", AUTHORITY, DATE, BODY),
        (SECRET, PATH, "192.168.1.x:8124", DATE, BODY),
        (SECRET, PATH, AUTHORITY, "Sun, 22 Nov 2026 19:04:12 GMT", BODY),
        (SECRET, PATH, AUTHORITY, DATE, BODY + b" "),
    ],
)
def test_verify_rejects_any_change_to_the_signed_string(
    secret, path, authority, date, body
):
    """Every part of the message is signed, the Date and the length included."""
    header = expected_signature(secret, path, authority, date, body)
    assert not verify_callback_signature(SECRET, header, PATH, AUTHORITY, DATE, BODY)


def test_a_reparsed_date_breaks_the_signature():
    """Why the Date is fed back verbatim: it is local time mislabelled GMT.

    The payload's own timestamp is an hour off it on a CET unit, so a verifier
    that parses and re-renders the header signs a different string.
    """
    header = expected_signature(SECRET, PATH, AUTHORITY, DATE, BODY)
    re_rendered = "Sun, 22 Nov 2026 18:04:11 GMT"  # the same instant, in real UTC
    assert not verify_callback_signature(
        SECRET, header, PATH, AUTHORITY, re_rendered, BODY
    )


@pytest.mark.parametrize(
    ("secret", "header", "date"),
    [
        (None, "anything", DATE),  # no subscription, so nothing is accepted
        (SECRET, None, DATE),  # unsigned
        (SECRET, "", DATE),
        (SECRET, "anything", None),  # no Date header
    ],
)
def test_verify_rejects_an_unsigned_or_unsubscribed_frame(secret, header, date):
    assert not verify_callback_signature(secret, header, PATH, AUTHORITY, date, BODY)


def test_verify_rejects_an_oversized_body_without_comparing():
    body = b"x" * (MAX_CALLBACK_BODY + 1)
    header = expected_signature(SECRET, PATH, AUTHORITY, DATE, body)
    assert not verify_callback_signature(SECRET, header, PATH, AUTHORITY, DATE, body)


def test_secret_is_fresh_and_long_enough_to_be_a_key():
    first, second = generate_secret(), generate_secret()
    assert first != second
    assert len(first) >= 32


def test_split_callback_url():
    assert split_callback_url(URL) == (PATH, AUTHORITY)
    assert split_callback_url("https://ha.example") == ("/", "ha.example")


def test_subscribe_body_carries_all_three_meta_fields():
    body = subscribe_body(["dp-1", "dp-2"], URL, SECRET)
    assert body["data"] == [
        {"id": "dp-1", "type": "datapoint"},
        {"id": "dp-2", "type": "datapoint"},
    ]
    assert body["meta"] == {"url": URL, "secret": SECRET, "type": SUBSCRIBE_TYPE}


def test_subscribe_body_keeps_a_plain_http_url_intact():
    """The firmware accepts and honours http:// against its own HTTPS-only spec."""
    assert subscribe_body([], "http://192.168.1.x:8123/x", SECRET)["meta"][
        "url"
    ].startswith("http://")


def test_parse_callback_body_reads_a_measured_frame():
    assert parse_callback_body(BODY) == [
        {"id": "dp-1", "value": "20", "timestamp": "2026-11-22T18:04:11Z"}
    ]


def test_parse_callback_body_keeps_the_value_a_string_in_engineering_units():
    """`dpt.scaling` arrives as a percent already, so nothing here rescales it."""
    raw = json.dumps({"data": {"id": "dp-1", "attributes": {"value": "20"}}}).encode()
    assert parse_callback_body(raw)[0]["value"] == "20"


def test_parse_callback_body_accepts_a_list():
    raw = json.dumps(
        {
            "data": [
                {"id": "a", "attributes": {"value": "on"}},
                {"id": "b", "attributes": {"value": "off"}},
            ]
        }
    ).encode()
    assert [item["id"] for item in parse_callback_body(raw)] == ["a", "b"]


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"not json",
        b"[]",
        b'{"data": null}',
        b'{"data": {"type": "datapoint", "attributes": {"value": "1"}}}',  # no id
        b'{"data": {"id": "dp-1"}}',  # no attributes
        b'{"data": {"id": "dp-1", "attributes": {}}}',  # no value: no state
        b'{"data": {"id": "", "attributes": {"value": "1"}}}',
    ],
)
def test_parse_callback_body_drops_anything_that_is_not_a_value(raw):
    assert parse_callback_body(raw) == []


def test_subscription_id_from_response():
    assert subscription_id_from_response({"data": {"id": "sub-1"}}) == "sub-1"
    assert subscription_id_from_response({"data": [{"id": "sub-2"}]}) == "sub-2"


@pytest.mark.parametrize(
    "payload",
    [None, {}, {"data": None}, {"data": {}}, {"data": [{}]}, {"data": {"id": ""}}],
)
def test_subscription_id_missing(payload):
    assert subscription_id_from_response(payload) is None


def test_callback_path_matches_on_the_path_not_the_authority():
    """A stale record is matched even when Home Assistant's address changed.

    That is the case that leaves an orphan behind in the first place, so the
    authority is deliberately not part of the comparison.
    """
    assert callback_path_matches(
        {"id": "s", "meta": {"url": "http://10.0.0.5:8123" + PATH}}, PATH
    )
    assert callback_path_matches({"id": "s", "meta": {"url": URL}}, PATH)


@pytest.mark.parametrize(
    "subscription",
    [
        None,
        {},
        {"meta": {}},
        {"meta": {"url": None}},
        {"meta": {"url": "http://192.168.1.x:8123/api/webhook/other-entry"}},
    ],
)
def test_callback_path_does_not_match_anything_else(subscription):
    """An unidentifiable record is left alone rather than deleted on a guess."""
    assert not callback_path_matches(subscription, PATH)


def test_chunked_is_a_fallback_that_never_yields_an_empty_batch():
    assert chunked(["a", "b", "c"], 2) == [["a", "b"], ["c"]]
    assert chunked([], 2) == []
    assert chunked(["a"], 1) == [["a"]]
