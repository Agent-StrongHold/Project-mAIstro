# Workspace

> Category: First-party product surface
> The design system for the Workspace — Home, Attention, the provenance
> timeline, session restore and sharing. A room you work in, not a tab you
> administrate. Use it for every surface a Workspace user sees; do not use it
> for generated marketing artifacts (those take a brand system from the catalog).

## Visual theme and atmosphere

Frosted glass over a soft colour bloom. The bloom is the persona's
atmosphere and is the one place the room is allowed to be beautiful; every
panel on top of it is quiet, translucent and disciplined. Nothing pulses,
glows for decoration, or animates on load. The room feels lit, not lit up.

The system's memorable element is the Attention stack: three or four
readable sentences in a large size, each carrying its age. Everything else
recedes so that those sentences are the first thing a person reads.

Personas wear their identity the way book covers do. Three templates ship —
greenhouse (the default), slate and studio — and a user may author their own
from four values. The grammar underneath never changes with the cover.

## Colour roles

The room has two kinds of colour and they are never confused:

**Taste — the persona's.** Field, bloom and accent. Greenhouse is fern over
moss with a hint of rose; slate is steel blue; studio is plum on oat paper.
The accent is worn by one primary action per view and by links. Nothing
decorative wears it.

- Greenhouse light: field `#EFF4EC`, accent `#2F7D4F` on white
- Greenhouse dark: field `#121A16`, accent `#8FD5A3` on `#0F1A13`
- Slate light: field `#EEF1F6`, accent `#2456C9`; dark: field `#161C2B`, accent `#7EA6FF`
- Studio light: field `#F4F0EA`, accent `#8A2F52`; dark: field `#1B1719`, accent `#E6A9BD`

**Meaning — the room's.** Fixed across every persona and scheme, because a
colour that means something cannot be a matter of taste:

- **You** — blue `#1D49B0` (dark `#A3C0FF`). A human acted.
- **Agent** — lilac `#5C4396` (dark `#C9B8EE`). An agent acted autonomously; always shown with "as [role]".
- **Gate** — teal-green `#14604C` (dark `#6FD3B8`). A policy allowed or blocked something, with its reason.
- **System** — grey `#4D5867` (dark `#B8BFCB`). Infrastructure acted on a schedule.
- **Warn** `#784D0E` (dark `#F2C46F`) — a stale wait, a blocked goal, a partial undo.
- **Success** `#14604C` (dark `#6FD3B8`) — confirmed, logged, verified.
- **Danger** `#A41F15` (dark `#FF9D94`) — irreversible actions only.

Ink is blue-black `#161B26`, never pure black. Secondary text is `#5A6376`;
the machine register is `#626C80` (dark `#98A0B3`). Text on the field and on
panels passes 4.5:1 in light and 6:1 in dark. Badge text sits on a 16% tint of
its own colour and is measured composited over the lightest surface: at least
5:1 in light and 5.5:1 in dark, on every persona. The test suite computes this. Purple and orange are
not in this system: the agent lilac is desaturated on purpose and there is no
warm-orange accent in any template.

## Typography

One reading face: Bricolage Grotesque, a variable font with an optical-size
axis. The greeting is set at opsz 96, weight 600, 38px, tracking -0.02em.
Everything else is opsz 14. There is no separate display face and no
uppercase, letter-spaced label anywhere in the system.

One machine face: JetBrains Mono, used only for the machine register — ids,
hashes, key=value pairs, seq numbers — at the 12px floor in the muted meta
colour. Never for buttons, labels, ages, filters or headings.

Scale (px): 12 · 13 · 15 · 16 · 18 · 24 · 38. A screen uses at most three
steps plus the machine register. **12px is the floor; nothing renders
smaller, including avatar initials and badge text.**

Registers:

- **Attention line** 18px, weight 500; the subject and the age in bold or warm.
- **Card sentence** 16px, weight 400, one human sentence, max 62 characters per line.
- **Prose** 15px; **secondary** 13px, muted.
- **Machine** 12px mono, meta colour, one line, joined with middle dots.

Both families ship with the Conductor from its own origin, never a CDN
(see FONTS.md; add `@fontsource-variable/bricolage-grotesque` alongside the
existing JetBrains Mono package).

## Component stylings

- **Glass panel.** `--glass` over the bloom, 1px `--edge`, 20px radius,
  18px backdrop blur, an inset 1px top highlight and one long soft shadow.
  Falls back to `--surface` where blur is unavailable. No panel has a hard
  drop shadow and no two elevations use the same radius.
- **Buttons.** Primary is a flat accent fill with `--accent-on` text, one
  per view. Secondary is `--glass-2` with an edge. Text buttons carry
  in-card actions ("Why this decision"). Quiet buttons are muted text
  ("Undo"). Danger is reserved for irreversible actions and names the
  action ("Remove sam"). Minimum height 36px; focus is the accent ring.
- **Badges.** Pill, 12px, 600, a 6px dot of the same colour before the
  word. Actor badges use the fixed quartet. In dark, the dot glows; in
  light it does not.
- **Attention item.** A 3px colour bar on the left in the item's
  colour, an 18px sentence with the subject in bold and the wait's age in
  warn colour when older than `--age-stale-after` (eight hours), a 14px muted second line, a
  chevron. The whole row is the target.
- **Provenance entry.** A glass panel on a vertical spine; the node dot is
  the actor colour. Header: name, badge, "as [role]" and the delegation
  note, time on the right. Then the sentence, the machine line, the
  actions, and, when open, the why-panel and the outcome.
- **Why-panel.** Unfolds inside the card like a footnote: a 3px left rule
  in the actor colour, a well background, three rows — Inputs, Constraint,
  Path — with the path in mono. Cited from the record, never generated.
- **Outcome lines.** Three: "Approved and logged" (success text, no box);
  "Undone by a compensating action" (success tint, with a verify link);
  "Can't fully undo" (warn tint, says why and that it is marked not fully
  undoable). There is no fourth.
- **Four faces.** Loading is a shimmer skeleton, never blank. Empty is a
  sentence plus a create action. Error/offline is a warn-tinted panel
  with retry and last-seen. No-permission is a system-tinted panel that
  names the missing scope. They never wear each other's face.
- **Inputs.** A well inside the glass: darker in dark, whiter in light.
  Focus is the accent ring; error is a danger edge with a sentence under
  it that says what to do.
- **Switcher.** A segmented glass control in the header with a colour dot
  per workspace. Reachable in at most six Tab presses from anywhere.
- **Ledger pill.** Success-tinted pill with a dot: "Ledger verified, 41
  records". Always visible in the header.

## Layout principles

- Header 64px, sticky, glass. Then the greeting and the resume bar, then
  the two-column room: Attention 5 / Timeline 7 at desktop. Everything
  left-aligned; max width 1280 with 40px gutters.
- At 980px the columns stack. At 640px the switcher drops under the
  identity row, timestamps move above each entry, and gutters are 16px.
  No horizontal scroll at 390px.
- Whitespace separates; hairlines only separate rows inside one panel.
- Ages, counts and times sit at the right edge of their row.

## Depth and elevation

Three levels: the bloom (0), glass panels (1), raised glass for menus,
toasts and dialogs (2). Level 2 is the same glass with a deeper shadow.
There is no level 3.

## Motion

150ms for hover and focus, 200ms for open/close, one easing curve. Motion
only answers an action: a why-panel unfolding, a toast arriving, a menu
opening. Nothing animates on page load and nothing loops.

## State honesty

Loading, empty, error and no-permission are four different faces and the
interface never wears the wrong one. A wait always carries its age. A
mutation always confirms itself in the same words as the action ("Approve"
produces "Approved and logged"). An action that cannot explain itself
does not ship: every agent and gate entry has a why-panel cited from the
record.

## Customising a persona theme

A user-authored theme supplies, per scheme: `--bg`, `--bloom`, `--accent`,
`--accent-on`, and optionally `--radius-sm`, `--radius-md`, `--radius-lg`.
It may not set the actor quartet, the four faces, the type floor, the focus
ring or the fonts. Reject a theme where `--accent-on` on `--accent` or
`--accent` on `--bg` falls under 4.5:1.

## Do and don't

- Do let the bloom be the only decoration.
- Do put the age on every wait and the reason on every gate.
- Do write outcomes in the same words as the action.
- Don't set any text under 12px.
- Don't use mono for labels, buttons or ages.
- Don't use uppercase tracked labels or numbered eyebrows.
- Don't add purple or orange; don't add a gradient to a button.
- Don't rebind an actor colour in a persona.

## Agent prompt guide

- Start from the greenhouse light tokens unless the workspace's persona
  says otherwise; rebind only the four persona values.
- One primary button per view. If you find two, one becomes secondary.
- Every agent or gate entry needs a why-panel with Inputs, Constraint,
  Path from the record. Do not invent a reason; leave the panel out and
  say "no reason recorded".
- Every wait shows its age; every undo says which of the three outcomes
  it is.
- If a value you need is not in this palette, use the nearest token and
  leave a comment; do not add a hex.
