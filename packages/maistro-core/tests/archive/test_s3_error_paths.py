"""The error branches in `S3ArchiveStore`, which a live server cannot reach.

The conformance suite next door deliberately refuses to mock the boto3 client:
its subject is whether a real S3-compatible service accepts what we send, and a
patched client proves only that a request was composed. That lesson stands, and
these tests are not an exception to it — they are about something else.

Each branch below is a decision *this module* makes about an exception the
client raised: is a `ClientError` a missing object or a real fault, does a
response body have a `close` to call, is an empty bucket name worth rejecting
before the first request. A live server cannot produce those situations on
demand — you cannot ask MinIO for a malformed `ClientError` — so the only way
to exercise them is a stub that raises what botocore would.

They were found by the diff-coverage gate, which reported five partial branch
arcs here: every one was the *re-raise* half of an error path, meaning the
suite had proved the happy path and the missing-object path and nothing about
what happens when S3 says something else.
"""

from __future__ import annotations

import pytest

from maistro.archive.s3 import S3ArchiveStore
from maistro.archive.types import ArchivedRecordNotFound, ArchiveError, ArchiveKey

SCOPE = "test-scope"


class _Boom(Exception):
    """A client error carrying whatever `response` the test needs.

    Modelled on `botocore.exceptions.ClientError`, which is matched by error
    *code* rather than by class: botocore generates its exception types per
    client, so `client.exceptions.NoSuchKey` is neither importable nor the same
    object across clients. That is exactly why `_is_missing` reads the dict, and
    why a stub can stand in for it faithfully.
    """

    def __init__(self, response: object) -> None:
        super().__init__("boom")
        self.response = response


class _Client:
    """A boto3 client stub that raises what it is told to."""

    def __init__(
        self,
        *,
        get_error: Exception | None = None,
        head_error: Exception | None = None,
        bucket_error: Exception | None = None,
    ):
        self.get_error = get_error
        self.head_error = head_error
        # A healthy bucket by default. `_head` confirms the bucket exists
        # before reporting a 404 as an absent object, so a stub without this
        # would make every miss look like an outage.
        self.bucket_error = bucket_error
        self.head_bucket_calls = 0

    def get_object(self, **_kwargs: object) -> object:
        if self.get_error is not None:
            raise self.get_error
        raise AssertionError("the test did not arrange a get_object outcome")

    def head_object(self, **_kwargs: object) -> object:
        if self.head_error is not None:
            raise self.head_error
        return {}

    def head_bucket(self, **_kwargs: object) -> object:
        self.head_bucket_calls += 1
        if self.bucket_error is not None:
            raise self.bucket_error
        return {}


def _store(**kwargs: object) -> S3ArchiveStore:
    return S3ArchiveStore("bucket", client=_Client(**kwargs))  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bucket", ["", "   ", "\t\n"])
def test_a_blank_bucket_is_refused_before_any_request(bucket: str) -> None:
    """Rejected at construction rather than at the first call.

    An empty bucket name reaches S3 as a malformed request whose error names
    the protocol rather than the configuration, so the operator reads a
    botocore traceback instead of "you did not set the bucket".
    """
    with pytest.raises(ArchiveError, match="non-empty"):
        S3ArchiveStore(bucket, client=_Client())  # type: ignore[arg-type]


# --------------------------------------------------------------------------
# Classifying the exception
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("response", "why"),
    [
        (None, "an exception with no response attribute at all"),
        ("not-a-dict", "a response that is a string"),
        (["Error"], "a response that is a list"),
    ],
)
def test_an_exception_without_a_dict_response_is_not_a_missing_object(
    response: object, why: str
) -> None:
    """`_is_missing` reads `response["Error"]["Code"]`, so a non-dict response
    must answer False rather than raising a TypeError inside the handler.

    Treating it as missing would be worse than either: a transport fault would
    surface as `ArchivedRecordNotFound`, and a caller would record "the archive
    does not have this" about an object that may well be there.
    """
    store = _store(get_error=_Boom(response))

    with pytest.raises(_Boom):
        store._get_bytes(ArchiveKey.for_payload(b"x", scope=SCOPE))


@pytest.mark.parametrize("code", ["NoSuchKey", "404", "NotFound"])
def test_the_documented_missing_codes_all_count(code: str) -> None:
    """head_object answers 404 where get_object answers NoSuchKey, and a
    caller must not have to know which verb produced the error."""
    store = _store(get_error=_Boom({"Error": {"Code": code}}))
    key = ArchiveKey.for_payload(b"x", scope=SCOPE)

    with pytest.raises(ArchivedRecordNotFound):
        store._get_bytes(key)


# --------------------------------------------------------------------------
# Re-raising what is not a missing object
# --------------------------------------------------------------------------


def test_get_re_raises_an_error_that_is_not_a_missing_object() -> None:
    """AccessDenied is not "no such object". Swallowing it into
    `ArchivedRecordNotFound` would turn a credentials or policy fault into a
    silent cache miss, and the archive would look empty rather than broken."""
    store = _store(get_error=_Boom({"Error": {"Code": "AccessDenied"}}))

    with pytest.raises(_Boom):
        store._get_bytes(ArchiveKey.for_payload(b"x", scope=SCOPE))


def test_head_re_raises_an_error_that_is_not_a_missing_object() -> None:
    """The same distinction on the `exists` path, where the cost is higher:
    `False` means "not archived", so a swallowed AccessDenied would invite a
    caller to re-archive data it cannot read."""
    store = _store(head_error=_Boom({"Error": {"Code": "AccessDenied"}}))

    with pytest.raises(_Boom):
        store._head(ArchiveKey.for_payload(b"x", scope=SCOPE))


def test_head_reports_false_for_a_missing_object() -> None:
    store = _store(head_error=_Boom({"Error": {"Code": "404"}}))

    assert store._head(ArchiveKey.for_payload(b"x", scope=SCOPE)) is False


def test_a_404_is_confirmed_against_the_bucket_before_reporting_absence() -> None:
    """`head_object` answers the same bare 404 for a key missing from a healthy
    bucket and for a bucket that does not exist, so the 404 alone cannot decide.
    Counting the call pins that the confirmation actually happens — a version
    that trusted the 404 would pass the assertion above and fail this one."""
    client = _Client(head_error=_Boom({"Error": {"Code": "404"}}))
    store = S3ArchiveStore("bucket", client=client)  # type: ignore[arg-type]

    assert store._head(ArchiveKey.for_payload(b"x", scope=SCOPE)) is False
    assert client.head_bucket_calls == 1


def test_a_hit_does_not_pay_for_the_bucket_check() -> None:
    """The confirmation is on the miss path only. An archive read is rare but
    an `exists()` that doubled its requests would double them for every
    caller, including the ones whose object is right there."""
    client = _Client()
    store = S3ArchiveStore("bucket", client=client)  # type: ignore[arg-type]

    assert store._head(ArchiveKey.for_payload(b"x", scope=SCOPE)) is True
    assert client.head_bucket_calls == 0


def test_an_unreachable_bucket_refuses_to_report_the_object_absent() -> None:
    """The failure this exists to prevent. A wrong bucket name, a deleted
    bucket or a credential that lost access must not report every archived
    record as missing — that is an outage wearing deletion's clothes, in the
    tier least likely to be watched."""
    store = _store(
        head_error=_Boom({"Error": {"Code": "404"}}),
        bucket_error=_Boom({"Error": {"Code": "NoSuchBucket"}}),
    )

    with pytest.raises(ArchiveError, match="not reachable"):
        store._head(ArchiveKey.for_payload(b"x", scope=SCOPE))


def test_the_refusal_does_not_echo_the_underlying_error_text() -> None:
    """The cause is chained, not interpolated. A botocore error can carry an
    endpoint, a request id, and in some configurations a presigned URL; the
    message an operator sees names the bucket and the situation."""
    store = _store(
        head_error=_Boom({"Error": {"Code": "404"}}),
        bucket_error=_Boom({"Error": {"Code": "AccessDenied", "Message": "sig=SECRETVALUE"}}),
    )

    with pytest.raises(ArchiveError) as caught:
        store._head(ArchiveKey.for_payload(b"x", scope=SCOPE))

    assert "SECRETVALUE" not in str(caught.value)
    assert isinstance(caught.value.__cause__, _Boom)


# --------------------------------------------------------------------------
# The response body
# --------------------------------------------------------------------------


class _BodyWithoutClose:
    """A streaming body that exposes no `close`.

    botocore's own `StreamingBody` has one, but the attribute is looked up
    rather than assumed precisely so a stub, a `BytesIO` wrapper, or a future
    botocore that returns something else does not crash the read in a `finally`
    — where the raised AttributeError would replace whatever error was already
    in flight.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class _BodyWithClose(_BodyWithoutClose):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _ReadingClient:
    def __init__(self, body: object) -> None:
        self._body = body

    def get_object(self, **_kwargs: object) -> dict[str, object]:
        return {"Body": self._body}


def test_a_body_without_close_is_read_rather_than_crashed_on() -> None:
    payload = b"hello"
    key = ArchiveKey.for_payload(payload, scope=SCOPE)
    store = S3ArchiveStore("bucket", client=_ReadingClient(_BodyWithoutClose(payload)))  # type: ignore[arg-type]

    assert store._get_bytes(key) == payload


def test_a_body_with_close_is_closed() -> None:
    """The other arc of the same branch: the stream is released rather than
    left to the garbage collector, which on a keep-alive connection is how a
    pool runs out of sockets under load."""
    payload = b"hello"
    key = ArchiveKey.for_payload(payload, scope=SCOPE)
    body = _BodyWithClose(payload)
    store = S3ArchiveStore("bucket", client=_ReadingClient(body))  # type: ignore[arg-type]

    assert store._get_bytes(key) == payload
    assert body.closed, "the body must be closed even though the read succeeded"
