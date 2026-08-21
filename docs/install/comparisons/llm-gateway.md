# LLM gateway choice (LiteLLM vs direct vs other)

Official signup / console links (no endorsement implied):

- [OpenAI platform](https://platform.openai.com/signup)
- [Anthropic console](https://console.anthropic.com/)
- [LiteLLM docs](https://docs.litellm.ai/)

## When LiteLLM helps

- **Multiple providers** behind one OpenAI-compatible surface.
- **Central key rotation**, budgets, and basic routing in one sidecar.
- Fits the default **maistro-engine** compose layout (`litellm` service on `127.0.0.1:4000`).

## When “direct” fits

- Single vendor, minimal moving parts, app calls provider SDKs or HTTPS directly.
- Strong compliance posture where an extra hop is discouraged.

## “Other” (installer stub)

Selecting `other` in answers yields a **preview** note only until a compose profile or gateway service is added. Verify your own gateway’s contract before routing production traffic.
