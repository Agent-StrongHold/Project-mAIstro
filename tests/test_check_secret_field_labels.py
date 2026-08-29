"""A credential field may not be named by its placeholder (#375).

Every password and API-key field in the Conductor's front end took its name
from placeholder text. A placeholder disappears the moment the field has a
value, and it can change with state — the LLM key field's read `API key` or
`key stored — replace?` depending on the server's answer, so the field's *name*
changed under the user.

The gate has two rules, and the tests below are mostly about the scanner they
share: reading JSX attributes correctly is the whole difficulty, and the first
version of it got that wrong in both directions.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check-secret-field-labels.py"


@pytest.fixture(scope="module")
def gate():
    spec = importlib.util.spec_from_file_location("check_secret_field_labels", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def surface(tmp_path: Path, body: str, name: str = "pages/Login.tsx") -> Path:
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- the committed state -----------------------------------------------------


def test_the_shipped_frontend_passes(gate) -> None:
    assert gate.main([]) == 0


# --- rule 1: no raw password input outside the shared components -------------


def test_a_raw_password_input_fails(gate, tmp_path: Path) -> None:
    surface(tmp_path, '<input type="password" value={v} />', "pages/Anything.tsx")

    findings = gate.raw_password_inputs(tmp_path, tmp_path / "components" / "shared.tsx")

    assert [f.line for f in findings] == [1]
    assert "SecretField" in findings[0].message


def test_the_shared_component_may_render_one(gate, tmp_path: Path) -> None:
    """It is the file that makes the others unnecessary — the show/hide toggle
    swaps `type` between `password` and `text`, so the string has to appear
    somewhere."""
    shared = surface(tmp_path, '<input type="password" />', "components/shared.tsx")

    assert gate.raw_password_inputs(tmp_path, shared) == []


# --- rule 2: a control on a credential surface must be able to carry a name --


def test_an_input_with_no_naming_attribute_fails(gate, tmp_path: Path) -> None:
    surface(tmp_path, '<input className="input-field" placeholder="password" />')

    findings = gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",))

    assert len(findings) == 1
    assert "placeholder is the only name" in findings[0].message


@pytest.mark.parametrize("attribute", ['id="x"', 'aria-label="Password"', 'aria-labelledby="y"'])
def test_any_of_the_three_naming_attributes_satisfies_it(gate, tmp_path: Path, attribute) -> None:
    surface(tmp_path, f"<input {attribute} placeholder='password' />")

    assert gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",)) == []


def test_a_naming_attribute_after_a_handler_still_counts(gate, tmp_path: Path) -> None:
    """The bug the scanner exists for. `onChange={(e) => ...}` contains a `>`,
    so a regex ending at the first one stops mid-tag — and since the naming
    attribute usually comes after the handler, that reads a labelled control as
    unlabelled. It reported two correctly-labelled controls on the real tree."""
    surface(tmp_path, '<input onChange={(e) => set(e.target.value)} id="conductor-name" />')

    assert gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",)) == []


def test_an_input_named_only_inside_a_comment_still_fails(gate, tmp_path: Path) -> None:
    """The comment must not supply the name the code does not have."""
    surface(tmp_path, '{/* id="not-real" */}\n<input placeholder="password" />')

    findings = gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",))

    assert [f.line for f in findings] == [2]


def test_an_input_written_inside_a_comment_is_not_a_finding(gate, tmp_path: Path) -> None:
    """A note explaining this very rule failed it on the first run."""
    surface(tmp_path, "{/* the <input> becomes a <select> when models load */}")

    assert gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",)) == []


def test_a_password_input_inside_a_comment_is_not_a_finding(gate, tmp_path: Path) -> None:
    surface(tmp_path, '// was: <input type="password" />\n', "pages/Anything.tsx")

    assert gate.raw_password_inputs(tmp_path, tmp_path / "components" / "shared.tsx") == []


def test_blanking_comments_keeps_line_numbers_honest(gate, tmp_path: Path) -> None:
    """Deleting them instead would report every later finding at the wrong
    line, which is worse than not reporting it: the reader goes looking."""
    body = "/* a\nmultiline\ncomment */\n<input placeholder='password' />"
    surface(tmp_path, body)

    findings = gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",))

    assert [f.line for f in findings] == [4]


def test_a_missing_credential_surface_fails(gate, tmp_path: Path) -> None:
    """The surface list is the gate's own scope. A file renamed out from under
    it would otherwise silently stop being checked."""
    findings = gate.placeholder_named_inputs(tmp_path, ("pages/Gone.tsx",))

    assert len(findings) == 1
    assert "missing" in findings[0].message


def test_an_unterminated_input_tag_is_read_to_the_end_of_the_file(gate, tmp_path: Path) -> None:
    """A half-written tag is a syntax error the type-checker will catch. This
    gate must not hang or crash on it first, and must not read it as named."""
    surface(tmp_path, '<input placeholder="password"')

    findings = gate.placeholder_named_inputs(tmp_path, ("pages/Login.tsx",))

    assert [f.line for f in findings] == [1]


def test_main_prints_every_finding_and_fails(gate, monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        gate, "audit", lambda: [gate.Finding("pages/Login.tsx", 12, "named by its placeholder")]
    )

    exit_code = gate.main([])
    printed = capsys.readouterr().out

    assert exit_code == 1
    assert "pages/Login.tsx:12: named by its placeholder" in printed
    # The remedy, not just the complaint: a gate that only says "no" sends the
    # reader to the source to work out what it wanted.
    assert "persistent associated label" in printed


def test_main_fails_when_the_frontend_is_missing(gate, monkeypatch, tmp_path: Path) -> None:
    """Better than passing vacuously. A moved or renamed tree would otherwise
    make this gate report OK about nothing at all."""
    monkeypatch.setattr(gate, "FRONTEND", tmp_path / "gone")

    assert gate.main([]) == 1


def test_the_gate_runs_as_a_script_too() -> None:
    import subprocess

    result = subprocess.run(
        [sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stdout + result.stderr
