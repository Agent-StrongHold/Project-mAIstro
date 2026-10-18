# Extension lifecycle

What happens between "a host discovers an extension" and "the host releases
it" — and what an extension may rely on at each stage. The ordering is the
security posture: **data about the extension is accepted before the
extension's code executes at all.**

## The stages

```
discover → validate manifest → resolve grants → load entrypoint → invoke → release
   (no code)     (no code)          (no code)        (first code)
```

### 1. Discover

The host finds extension packages (an installed distribution, a directory).
Nothing runs: discovery is path and metadata reading only. An extension
package is a buildable project — its `pyproject.toml` and manifest are files,
not behavior.

### 2. Validate the manifest (no code loads)

`extension.json` is parsed and checked against the SDK's schema: shape
strictness (`extra="forbid"`), the closed authority vocabularies, the
identity patterns, and the contract range. The entrypoint's `module` is
checked *lexically* — it is never imported during validation. A malformed
manifest, an unknown capability, or an unsupported contract major fails here,
before any extension code can influence its own acceptance.

### 3. Resolve grants (no code loads)

The host turns the manifest's *declarations* into *grants*: capabilities,
effects, data scopes, network allowlists, filesystem modes, secret
references. Declaring nothing yields nothing. The host may grant less than
declared (policy, user consent, least authority); it never grants what was
not declared — extension code cannot receive undeclared authority merely by
importing SDK objects, because authority flows from the manifest, not from
the import.

### 4. Load the entrypoint (first code runs)

Only now does the host import the entrypoint module and fetch the named
object. By the time your code executes, your authority is fixed and observable
in the grant record. The entrypoint object is plain data naming what a host
may call (see the reference extension's `PLUGIN`), so loading it has no side
effects to reason about.

### 5. Invoke

The host calls the declared handler, passing the canonical extension context
— the object that exposes only the granted Workspace/Agent/Run data. There is
no second way to reach product state: the context is the seam, which is what
makes an extension's behavior reviewable from its manifest plus its handler.

### 6. Release

The host drops the loaded module and its grants. An extension holds no state
across releases; anything durable goes through declared, host-owned stores.

## What the SDK pins vs. what M9-A2 pins

The manifest, the contract version, and the validation pipeline are the
M9-A1 SDK package (`maistro-ext-sdk`, #949). The exact signatures of the
context object and the lifecycle hooks an entrypoint receives are the M9-A2
lifecycle contracts (#950); until those are adopted, keep entrypoints
data-only (as the reference extension does) so adopting them is an
annotation change, not a rewrite.

## Examples

The reference extension (`extensions/reference-greeter/`) demonstrates the
whole cycle for the smallest honest case: a `tool` extension with zero
capabilities, a `read-only` effect, and one pure handler. Extensions that
need more authority are the same shape with a longer manifest — see
[capabilities.md](capabilities.md) for worked declarations.
