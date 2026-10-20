# gallery-model-adapter

The reference gallery's **provider adapter** extension
(`capability-provider` family). It ships its provider spec as plain data
plus pure normalization functions; the host validates it through the
provider-adapter SDK's registration conformance (ADR-104) and registers it
through `register_adapter_models` — one registration seam, canonical
routing unchanged. See the [gallery README](../../README.md).
