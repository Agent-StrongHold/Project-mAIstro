# 68 — deployment-policy resource overrides

Four more maistro-core node IDs close #68's deployment-policy gap: raising the
byte or depth ceiling now fails without the explicit unsafe-resource override,
the explicit override is covered, and malformed override values fail startup
instead of silently selecting a policy.
