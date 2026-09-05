---
id: SPEC-001
title: Dynamic Local LLM Healthcheck, Tunnel & Gemini Failover
status: complete
priority: high
created: 2026-09-04
tags: [backend, ai, negotiation, multimodal, failover]
assigned: agent
---

# Context & Objectives
Nego-Lah supports a self-hosted vision-language model (`Qwen3.6-35B-A3B`) exposed locally or remotely via a Cloudflare Tunnel (e.g. `https://llm.negolah.my`). Because the local model container may be started or stopped on demand, the backend must dynamically probe model availability with an async healthcheck, cache the health status for 30s to eliminate latency on user chats, and seamlessly fail over to Google Gemini (`gemini-3.8-flash`) whenever the tunnel or local container is offline. Both models must support multimodal image processing for listing analysis.

# Acceptance Criteria
- [x] `llm_factory.get_chat_model()` dynamically probes `LOCAL_LLM_BASE_URL` with a 1.5s timeout.
- [x] Probe results are cached in Redis (or in-process memory) for 30 seconds (`health:local_llm`).
- [x] When probe is successful, returns `ChatOpenAI` targeting the local model with `streaming=True`.
- [x] When probe fails (timeout, 5xx, or network error), returns `ChatGoogleGenerativeAI` targeting `gemini-3.8-flash`.
- [x] Listing image analyzer formats multimodal inputs using standard OpenAI `image_url` spec compatible with both Qwen and Gemini.

# Technical Design & Contracts
- **Health Probe Endpoint:** `GET {LOCAL_LLM_BASE_URL}/health` or `GET {LOCAL_LLM_BASE_URL}/models`
- **Cache Key:** `health:local_llm` (TTL: 30s)
- **Multimodal Payload Structure:**
  ```json
  [
    {"type": "text", "text": "Analyze this listing photo"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
  ]
  ```

# Test-Driven Development (TDD) Scenarios
- [ ] **Scenario 1:** When `LOCAL_LLM_BASE_URL` returns HTTP 200 within 1.5s, `get_chat_model()` returns `ChatOpenAI` and caches status `1` for 30s.
- [ ] **Scenario 2:** When `LOCAL_LLM_BASE_URL` times out or errors, `get_chat_model()` logs a warning and returns `ChatGoogleGenerativeAI`.
- [ ] **Scenario 3:** Subsequent requests within 30s reuse cached health status without making HTTP probe calls.
- [ ] **Scenario 4:** Image analyzer delivers multimodal inputs to the model without format conversion errors.

# Implementation Files
- `backend/domains/negotiation/llm_factory.py` - Core factory & probe logic
- `backend/agent/tools/image_analyzer.py` - Multimodal format alignment
- `backend/tests/test_dynamic_llm_factory.py` - Unit and mock failover tests
