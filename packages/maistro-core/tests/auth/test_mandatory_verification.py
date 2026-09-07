"""#856 — OIDC verification dependencies are mandatory: fail closed, never downgrade.

These tests remove the verification dependency itself and prove authentication
is refused, not downgraded to unverified-claims parsing:

- PyJWT removed  -> ``maistro.auth.oauth`` (and every lazy export that could
  produce a verifier) refuses to import with an actionable error.
- ``cryptography`` removed (the ``pyjwt[crypto]`` backend) -> a real JWKS
  verification attempt raises ``OAuthTokenValidationError`` naming the missing
  backend; it never returns claims.

Subprocess isolation is the point, for the same reason as
``tests/archive/test_optional_dependency.py``: within this suite's interpreter
the modules are already in ``sys.modules``, so an in-process ``sys.modules``
patch would prove nothing about a clean install. The child interpreter gets a
``meta_path`` blocker that makes the dependency unimportable before any
``maistro`` import runs.
"""

from __future__ import annotations

import base64
import json
import os
import pathlib
import subprocess
import sys
import time

import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

import maistro

_SRC = str(pathlib.Path(maistro.__file__).resolve().parent.parent)

_ISSUER = "https://idp.example.com"
_CLIENT_ID = "maistro-client"
_JWKS_URL = "https://idp.example.com/jwks"


def _run(
    statement: str, extra_env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([_SRC, env.get("PYTHONPATH", "")]).rstrip(os.pathsep)
    env.update(extra_env or {})
    return subprocess.run(  # fixed argv, no shell
        [sys.executable, "-c", statement],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def _blocker(*roots: str) -> str:
    """meta_path finder making ``roots`` unimportable in the child process.

    ``ModuleNotFoundError`` (not plain ``ImportError``) so consumers that probe
    for an optional backend with ``except ModuleNotFoundError`` — PyJWT's
    ``has_crypto`` — see the dependency as absent, which is the real
    no-cryptography-install behaviour.
    """

    names = json.dumps(list(roots))

    return (
        "import sys\n"
        f"_BLOCKED = {names}\n"
        "class _Blocked:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in _BLOCKED:\n"
        "            raise ModuleNotFoundError(f'blocked: {name}', name=name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, _Blocked())\n"
    )


def test_pyjwt_removed_refuses_import_of_the_oauth_module() -> None:
    """Removing PyJWT must make the OIDC path fail closed at import with an
    actionable error — there is no claims-only fallback to downgrade to."""
    statement = _blocker("jwt") + (
        "import maistro.auth\n"
        "try:\n"
        "    import maistro.auth.oauth\n"
        "except ImportError as exc:\n"
        "    msg = str(exc)\n"
        "    assert 'pyjwt' in msg.lower(), msg\n"
        "    assert 'fails closed' in msg.lower(), msg\n"
        "else:\n"
        "    raise SystemExit('oauth module imported without pyjwt')\n"
        "# The lazy package exports must not smuggle out a verifier either.\n"
        "try:\n"
        "    maistro.auth.OAuth2Client\n"
        "except (ImportError, AttributeError):\n"
        "    pass\n"
        "else:\n"
        "    raise SystemExit('lazy OAuth export succeeded without pyjwt')\n"
        "print('REFUSED')\n"
    )
    result = _run(statement)
    assert result.returncode == 0, result.stderr
    assert "REFUSED" in result.stdout


def test_cryptography_removed_verification_refuses_not_downgrades() -> None:
    """Without the ``pyjwt[crypto]`` backend a JWKS verification attempt must
    raise ``OAuthTokenValidationError`` naming the unavailable backend — never
    return claims or fall back to unverified parsing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()

    def b64(n: int, length: int) -> str:
        return base64.urlsafe_b64encode(n.to_bytes(length, "big")).rstrip(b"=").decode()

    jwks = {
        "keys": [
            {
                "kty": "RSA",
                "kid": "kid-1",
                "use": "sig",
                "alg": "RS256",
                "n": b64(pub.n, 256),
                "e": b64(pub.e, 3),
            }
        ]
    }
    now = int(time.time())
    token = pyjwt.encode(
        {"iss": _ISSUER, "aud": _CLIENT_ID, "sub": "sub-1", "exp": now + 300, "iat": now},
        key,
        algorithm="RS256",
        headers={"kid": "kid-1"},
    )

    statement = _blocker("cryptography") + (
        "import asyncio, json, os\n"
        "import httpx\n"
        "from maistro.auth.oauth import (\n"
        "    JWKSIdTokenVerifier,\n"
        "    OAuthProviderConfig,\n"
        "    OAuthTokenValidationError,\n"
        ")\n"
        "\n"
        "jwks = json.loads(os.environ['TEST_JWKS'])\n"
        "token = os.environ['TEST_TOKEN']\n"
        "config = OAuthProviderConfig(\n"
        "    name='test',\n"
        "    authorization_url='https://idp.example.com/authorize',\n"
        "    token_url='https://idp.example.com/token',\n"
        f"    client_id={_CLIENT_ID!r},\n"
        f"    jwks_url={_JWKS_URL!r},\n"
        f"    issuer={_ISSUER!r},\n"
        "    require_id_token=True,\n"
        ")\n"
        "\n"
        "async def main():\n"
        "    def handler(request):\n"
        "        return httpx.Response(200, json=jwks)\n"
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:\n"
        "        try:\n"
        "            await JWKSIdTokenVerifier().verify(token, config, http, None)\n"
        "        except OAuthTokenValidationError as exc:\n"
        "            msg = str(exc)\n"
        "            assert 'unavailable' in msg, msg\n"
        "            assert 'cryptography' in msg, msg\n"
        "            assert 'never accepted' in msg, msg\n"
        "            print('REFUSED:', msg)\n"
        "            return\n"
        "    raise SystemExit('DOWNGRADED: verification succeeded without cryptography')\n"
        "\n"
        "asyncio.run(main())\n"
    )
    result = _run(statement, extra_env={"TEST_JWKS": json.dumps(jwks), "TEST_TOKEN": token})
    assert result.returncode == 0, result.stderr
    assert "REFUSED" in result.stdout
    assert "DOWNGRADED" not in result.stdout


async def test_missing_jwks_dependency_in_flow_refuses_authentication() -> None:
    """In-flow: when the JWKS is unreachable mid-login the exchange must raise
    (provider unavailable) rather than authenticate from unverified claims.
    The token endpoint succeeds and returns an id_token — the refusal happens
    exactly at the verification step that must not be skipped."""
    import httpx

    from maistro.auth.oauth import (
        InMemoryStateStore,
        JWKSIdTokenVerifier,
        OAuth2Client,
        OAuthProviderConfig,
        OAuthTokenValidationError,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("/token"):
            # Provider happily returns an id_token; only verification is down.
            return httpx.Response(
                200,
                json={"access_token": "at", "token_type": "Bearer", "id_token": "h.p.s"},
            )
        raise httpx.ConnectError("JWKS endpoint down")

    config = OAuthProviderConfig(
        name="test",
        authorization_url="https://idp.example.com/authorize",
        token_url="https://idp.example.com/token",
        client_id=_CLIENT_ID,
        jwks_url=_JWKS_URL,
        issuer=_ISSUER,
        require_id_token=True,
    )
    client = OAuth2Client(
        providers={"test": config},
        state_store=InMemoryStateStore(),
        http=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        secret_resolver=lambda name: None,
        id_token_verifier=JWKSIdTokenVerifier(),
    )
    _, state = await client.authorize_url("test", "https://conductor.local/cb")
    with pytest.raises(OAuthTokenValidationError, match="JWKS"):
        await client.exchange_code("test", "code", state, "https://conductor.local/cb")
