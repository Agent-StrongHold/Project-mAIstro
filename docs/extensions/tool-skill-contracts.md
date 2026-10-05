# Tool and Skill contracts (M9-E3)

What the host does with a `tool`- or `skill`-family package after its
manifest is accepted: how it is registered, how its **capability/effect
classification** is computed, who may see and call it, and what one call
crosses on the way to an effect. The manifest is the package's *claim*
([manifest reference](manifest-reference.md)); this page is the host side
that turns the claim into enforced behavior. The implementation lives in
`maistro.extensions.tool_skill` (product-private, as the namespace policy
requires).

## The one rule underneath everything

**Classification is host-owned.** The host computes what your package is
from the *union* of everything it asks for — its declared `effects` and its
requested `capabilities` — and never from your self-description alone:

| Manifest asks for | Effect floor (host-computed) |
|-------------------|------------------------------|
| nothing declared, no capabilities | `irreversible` for tools (ADR-050 safe default), `read-only` for skills |
| `effects: ["read-only"]` only | `read-only` |
| any `*.write` capability or `tool.invoke` | at least `mutating` |
| `network.outbound` or `secrets.read` | at least `external-side-effect` |
| `effects: ["irreversible"]` | `irreversible` |

The floor maps onto the canonical ADR-050 reversibility tiers that Bindings
and policy reason about: `read-only` → `internal`, `mutating` /
`external-side-effect` → `reversible`, `irreversible` → `irreversible`.

At call time your handler may state an *effect claim* — what this one call
does. The host validates it against the floor:

- a claim **below** the floor is refused before anything dispatches (no
  Invocation, no provider call) — a higher-risk effect cannot relabel itself
  reversible to evade policy;
- a claim **above** the floor is adopted, so an extension that knows one call
  is destructive can take the stricter gate for that call.

The only way a classification moves downward is a host-side operator
override. That is host configuration, not extension input.

Inspect any package's classification before installing it:

```console
$ maistro extensions contract extensions/reference-greeter/extension.json
reference.greeter@1.0.0
  family:        tool
  ...
  host classification: effect floor read-only -> reversibility internal (ADR-050)
```

The command validates the manifest and reads nothing else — the entrypoint
module is never imported for inspection. Data about the code comes before
the code.

## Registration: adding a package, not editing the host

Registration is data-driven on both families:

- **Tools** — the host feeds the accepted manifest plus its entrypoint object
  (`PLUGIN`) and the loaded handler into the tool catalog. Re-registering the
  identical package is idempotent; a *different* package under a registered
  id is refused — upgrades go through the install lifecycle, never a silent
  overwrite.
- **Skills** — the accepted manifest plus its entrypoint object projects into
  the product skill registry. The trust tier is the **host's** publisher-trust
  decision, never read from the package, and the registry's own tier rules
  still apply (a `t2` extension skill cannot overwrite a `t0` built-in).

A Skill may compose canonical tools: its entrypoint object lists the tool
names it invokes. Composition is validated **at registration** against the
same allowlists as direct tool access, so a Skill whose composition exceeds
its grants fails loudly before it is ever offered to a model.

## Access: allowlists and manifest permissions

Tool access is constrained twice, and both gates fail closed:

1. **Workspace allowlist** — an extension id is callable in a Workspace only
   if that Workspace's allowlist names it. A Workspace without an allowlist
   has zero third-party tools, not all of them.
2. **Agent allowlist** — where an Agent's allowlist is set, it further narrows
   the Workspace's. A tool outside either allowlist is *absent* from
   exposures — the model never sees a name it could not lawfully call.

Manifest permissions cap everything: an exposure can only name authorities
the package's own manifest requested, and the entrypoint object was already
validated against the manifest (a handler claiming capabilities the manifest
never asked for is a validation error, not a runtime surprise).

## Execution: one governed path

Every tool call — extension or built-in — crosses the accepted
`Capability -> Provider -> Binding -> Invocation` seam
(ADR-081226-6b46):

```text
registered tool -> Binding (capability "extension.tool:<id>",
                         config: host classification + permissions)
      -> policy decision (allow / deny / require-approval)
      -> one Invocation (run_id, node_run_id, attempt_id, actor)
      -> your handler, dispatched under the host deadline
```

What comes back is canonical and attributable in every terminal case:

| Outcome | Meaning | Attribution |
|---------|---------|-------------|
| `completed` | usable result | the Invocation record |
| `denied` | policy refused | execution scope + the classification the decision ran on |
| `approval_required` | durable request pending a human | the approval request id |
| `failed` | handler/deadline-family failure | typed `error_code`, Invocation row (UNKNOWN after dispatch — the remote effect may have landed) |
| `cancelled` | deadline expiry or cancellation | the interrupted Invocation (recorded UNKNOWN — never claimed as a clean outcome) |

Cancellation stays cancellation: the call re-throws `CancelledError` with the
canonical outcome attached (`exc.outcome`), so run-level cancellation
accounting keeps working while the disposition stays attributable.

## Conformance

Built-in and external implementations pass the **same** protocol conformance
battery where semantics overlap: exposure names a canonical classification,
results carry Invocation attribution, errors are typed, refusals stay
attributable, cancellation is never reported as success. A tool that cannot
produce a scenario fails that check — subjects do not grade their own
homework. Run the suite over your own surface with
`maistro.extensions.tool_skill.run_conformance`; the reference extension's
registration path is exercised against the real out-of-tree package in
`packages/maistro-core/tests/extensions/test_tool_skill_conformance.py`.
