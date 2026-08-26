"""The policy type refuses the policies that are not policies (#310).

Every test here is a way a CSP gets hollowed out while still looking like one,
because that is the only interesting failure mode: a header that is present and
permissive passes any check that asks whether the header is set, and reads as
protection to everyone downstream.
"""

from __future__ import annotations

import pytest

from maistro.security.content_security_policy import (
    NONE,
    SELF,
    ContentSecurityPolicy,
    InsecurePolicyError,
)


def _floor(**overrides: tuple[str, ...]) -> dict[str, tuple[str, ...]]:
    """The five directives every policy must state, plus whatever a test adds."""
    base: dict[str, tuple[str, ...]] = {
        "default-src": (SELF,),
        "object-src": (NONE,),
        "base-uri": (SELF,),
        "form-action": (SELF,),
        "frame-ancestors": (NONE,),
    }
    base.update(overrides)
    return base


class TestTheDirectivesThatMustBeStated:
    @pytest.mark.parametrize(
        "omitted", ["default-src", "object-src", "base-uri", "form-action", "frame-ancestors"]
    )
    def test_omitting_one_is_refused_and_the_message_names_it(self, omitted: str) -> None:
        directives = _floor()
        del directives[omitted]

        with pytest.raises(InsecurePolicyError) as caught:
            ContentSecurityPolicy.build(directives)

        assert omitted in str(caught.value)

    def test_the_message_names_every_omission_at_once(self) -> None:
        """One at a time would mean five edit-and-rerun cycles to learn what a
        new policy is missing."""
        with pytest.raises(InsecurePolicyError) as caught:
            ContentSecurityPolicy.build({"script-src": (SELF,)})

        message = str(caught.value)
        assert all(name in message for name in _floor())


class TestTheSourcesThatUndoThePolicy:
    def test_unsafe_inline_in_script_src_is_refused(self) -> None:
        """The one that returns the policy to no policy against injected
        markup, which is the whole reason the header is served."""
        with pytest.raises(InsecurePolicyError, match="unsafe-inline"):
            ContentSecurityPolicy.build(_floor(**{"script-src": (SELF, "'unsafe-inline'")}))

    def test_unsafe_inline_in_style_src_is_allowed(self) -> None:
        """Deliberately not refused. An inline style is a real weakening and a
        far smaller one than an inline script, and a type that forbids it would
        be routed around by applications that genuinely need it — at which
        point the script-src rule goes with it. This policy does not use it;
        the type does not pretend nobody may."""
        policy = ContentSecurityPolicy.build(_floor(**{"style-src": (SELF, "'unsafe-inline'")}))

        assert "'unsafe-inline'" in policy.sources_for("style-src")

    @pytest.mark.parametrize("directive", ["script-src", "default-src", "style-src", "worker-src"])
    def test_unsafe_eval_is_refused_wherever_it_appears(self, directive: str) -> None:
        with pytest.raises(InsecurePolicyError, match="unsafe-eval"):
            ContentSecurityPolicy.build(_floor(**{directive: (SELF, "'unsafe-eval'")}))

    def test_a_fetch_directive_with_no_sources_is_refused(self) -> None:
        """A bare `img-src` is served as a name with nothing after it, which a
        browser reads as `'none'`. That is a valid policy and almost never the
        one the author meant, so it has to be said out loud."""
        with pytest.raises(InsecurePolicyError, match="img-src"):
            ContentSecurityPolicy.build(_floor(**{"img-src": ()}))


class TestValuelessDirectives:
    def test_upgrade_insecure_requests_needs_no_sources(self) -> None:
        """The exception to the rule above: this directive carries its meaning
        in being present at all."""
        policy = ContentSecurityPolicy.build(_floor(**{"upgrade-insecure-requests": ()}))

        assert policy.header_value().endswith("upgrade-insecure-requests")

    def test_it_is_serialised_without_a_trailing_space(self) -> None:
        """`"upgrade-insecure-requests "` is not a parse error, but a header a
        person cannot diff against the policy they wrote is a header nobody
        checks."""
        policy = ContentSecurityPolicy.build(_floor(**{"upgrade-insecure-requests": ()}))

        assert "  " not in policy.header_value()
        assert "; " in policy.header_value()


class TestTheHeaderItCarries:
    def test_directives_keep_the_order_they_were_written_in(self) -> None:
        """Sorted output would put `'self'` in the middle of a list of origins
        and separate directives that belong together. A policy is read by
        people at least as often as by browsers."""
        policy = ContentSecurityPolicy.build(
            {
                "default-src": (SELF,),
                "script-src": (SELF,),
                "object-src": (NONE,),
                "base-uri": (SELF,),
                "form-action": (SELF,),
                "frame-ancestors": (NONE,),
            }
        )

        assert policy.header_value().startswith("default-src 'self'; script-src 'self';")

    def test_multiple_sources_are_space_separated_within_a_directive(self) -> None:
        policy = ContentSecurityPolicy.build(_floor(**{"img-src": (SELF, "data:", "blob:")}))

        assert "img-src 'self' data: blob:" in policy.header_value()

    def test_the_enforcing_and_reporting_names_come_from_one_place(self) -> None:
        """Spelling the report-only name at a call site is how a policy ends up
        served under it permanently."""
        assert ContentSecurityPolicy.header_name(report_only=False) == "Content-Security-Policy"
        assert (
            ContentSecurityPolicy.header_name(report_only=True)
            == "Content-Security-Policy-Report-Only"
        )

    def test_a_directive_that_was_not_stated_reports_no_sources(self) -> None:
        policy = ContentSecurityPolicy.build(_floor())

        assert policy.sources_for("script-src") == ()
        assert policy.sources_for("default-src") == (SELF,)

    def test_a_built_policy_cannot_be_edited_afterwards(self) -> None:
        """Validation at construction is worth nothing if a caller can widen
        the result on the way to the header."""
        policy = ContentSecurityPolicy.build(_floor())

        with pytest.raises((AttributeError, TypeError)):
            policy.directives = ()  # type: ignore[misc]
