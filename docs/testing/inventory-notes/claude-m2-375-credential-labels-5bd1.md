---
inventory-delta:
  tests/: +17
---
# claude-m2-375-credential-labels-5bd1

Every password and API-key field in the Conductor took its accessible name from
placeholder text. A placeholder is not a name: it disappears the moment the
field has a value — so a screen-reader user who tabs back to a half-filled form
is told nothing — and it can change with state. The LLM key field read
`API key` or `key stored — replace?` depending on the server's answer, so the
field's *name* changed under the user. The setup wizard had two fields whose
entire name was `password`, one for the admin account and one for the daily
user.

**`tests/test_check_secret_field_labels.py` (+17)** covers
`scripts/check-secret-field-labels.py`, and most of it is about the scanner the
gate's two rules share, because reading JSX attributes correctly is the whole
difficulty and the first version got it wrong in both directions:

- the two rules themselves — a raw `type="password"` outside the shared
  components fails; `shared.tsx` may render one, since the show/hide toggle
  swaps `type` and the string has to live somewhere;
- an input with no `id`, `aria-label` or `aria-labelledby` on a credential
  surface fails, and each of those three attributes on its own clears it;
- **a naming attribute after an event handler still counts.** This is the bug
  the scanner exists for: `onChange={(e) => …}` contains a `>`, so a regex
  ending at the first one stops mid-tag, and since the naming attribute usually
  comes after the handler it read labelled controls as unlabelled. Measured: the
  regex version reported five findings on this tree, two of which were
  correctly-labelled controls;
- **comments are blanked, not deleted, and not trusted.** A `{/* … <input> … */}`
  note explaining this very rule failed the gate on its first run. An `id=`
  inside a comment must not satisfy the rule it explains, and blanking rather
  than deleting keeps every later finding's line number honest — a wrong line
  number is worse than no finding, because the reader goes looking;
- a credential surface that no longer exists fails, so a renamed file cannot
  silently drop out of the gate's scope, and a missing frontend tree fails
  rather than reporting OK about nothing;
- an unterminated `<input` tag is read to the end of the file rather than
  hanging or crashing, and is not read as named;
- the failure path prints each finding *and* the remedy — a gate that only says
  "no" sends the reader to the source to work out what it wanted.

**Not counted here, because it is a Playwright spec rather than a pytest node:**
`packages/hive-conductor/tests/e2e/credential-labels.spec.ts` asks the browser's
own accessibility tree what each field is called — the only thing that settles
it, since a label can be present, associated with the wrong control, and score
perfectly on a source scan. It checks that no field's name is merely its
placeholder, that the sign-up form's two password fields are told apart, that
revealing a secret is a real `type` change which preserves `autocomplete`, that
the reveal control names the field it belongs to, that axe finds nothing on the
sign-in form, and that every field on the credentials page — the surface behind
authentication, where the placeholder changed with server state — is named.

`session.ts` changed as a direct consequence. Its setup helper used to fill the
two account passwords with `input[type="password"]` `nth(0)`/`nth(1)`, because
both fields had `placeholder="password"` and nothing else to tell them apart —
a test identifying a credential field by its position in the DOM is the same
defect seen from the other side. It selects by label now.
