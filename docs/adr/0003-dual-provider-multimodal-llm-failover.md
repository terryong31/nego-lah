# 3. Dual-Provider Multimodal LLM Factory with Dynamic Failover

- Status: Accepted
- Date: 2026-09-04
- Deciders: Terry (owner), AI Agent

## Context

Nego-Lah uses AI for autonomous price negotiations and listing image analysis. We wanted to leverage a self-hosted vision-language model (`Qwen3.6-35B-A3B`) hosted on local hardware or exposed via Cloudflare Tunnel (`https://llm.negolah.my`), while maintaining high availability via Google Gemini (`gemini-3.8-flash`).

The self-hosted model container is run on-demand (may be started or stopped at any time), so the backend must not crash or delay customer interactions when the local instance is offline.

### Decision Drivers

- **Multimodal Capabilities:** Both negotiation chat and listing image analysis require vision-language support (processing both text and base64/URL images). `Qwen3.6-35B-A3B` natively supports conversational image understanding using OpenAI-compatible payload schemas.
- **Latency & Reliability:** Probing a downed tunnel on every customer message would add multi-second delays or fail the chat stream.
- **Failover Transparency:** Seamless fallback to Google Gemini when the tunnel or container is unavailable.

## Decision

We implemented a **Dynamic LLM Factory** in `backend/agent/llm_factory.py`:

1. **Active Probing:** The factory queries `GET {LOCAL_LLM_BASE_URL}/models` with a strict 1.5s timeout.
2. **TTL Health Caching:** Probe outcomes (`1` for healthy, `0` for down) are cached in Redis under `health:local_llm` for 30 seconds. Subsequent chat turns read the cache with sub-millisecond overhead.
3. **Dual Driver Support:**
   - When healthy: returns `ChatOpenAI` targeting the local/tunnel endpoint with `streaming=True`.
   - When offline/unreachable: transparently falls back to `ChatGoogleGenerativeAI` (`gemini-3.8-flash`).
4. **Uniform Multimodal Format:** Uses standard LangChain/OpenAI `image_url` message structures across both providers.

## Consequences

- **Positive:** Maximum privacy and cost savings when local model is active; zero downtime or degraded user experience when the local container is closed.
- **Negative:** Provider switching mid-conversation could produce slight stylistic differences between Qwen and Gemini responses.
