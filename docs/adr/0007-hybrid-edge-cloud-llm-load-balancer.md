# 7. Hybrid Edge-Cloud LLM Load Balancer with Atomic Concurrency Leases

- Status: Accepted
- Date: 2026-09-05
- Deciders: Terry (owner), AI Agent
- Consulted: SPEC-001, SPEC-020, ADR-0003

## Context

Nego-Lah features an autonomous negotiation agent powered by an AI model. For portfolio demonstration and real-world deployment, the primary model (`Qwen3.6-35B-A3B-4bit`) is self-hosted on an Apple Silicon M5 MacBook Pro (32GB Unified Memory) and exposed via Cloudflare Tunnel (`https://llm.negolah.my`). The API server runs on an **AWS Lightsail** instance (FastAPI + Redis + Caddy).

Up to 20 users are expected to test the application concurrently during demonstrations and evaluations. 

In [ADR-0003](0003-dual-provider-multimodal-llm-failover.md), we established health probing and failover to Google Gemini (`gemini-3.8-flash`) when the local endpoint is offline. However, ADR-0003 assumed binary health (online vs offline) and did not address **GPU compute saturation under concurrent load**:
- On Apple Silicon with 10 GPU cores and Unified Memory, local MLX inference runs **unbatched**. A single generation stream runs smoothly at ~50–70 tokens/second.
- If 2 or more requests stream tokens simultaneously, memory bandwidth is divided, latency balloons, and 3+ concurrent requests cause thermal throttling and memory pressure.
- We need an intelligent load-balancing mechanism to protect the local laptop while providing a responsive, zero-delay experience for all 20 concurrent users.

### Decision Drivers

- **Zero User Queuing Delay:** When the local model is busy generating, concurrent users should not wait in a queue; their requests must be served instantly.
- **Hardware Protection:** Prevent thermal degradation, memory swap thrashing, or OOM crashes on the self-hosted Apple Silicon host.
- **Multi-Worker Process Safety:** AWS Lightsail runs Uvicorn with multiple worker processes (`WEB_CONCURRENCY=4`); in-flight generation state must be shared across processes atomically without IPC complexity.
- **Demonstrable Engineering Value:** Showcasing a working hybrid edge/cloud orchestration architecture where private local inference is prioritized and public cloud handles traffic surges.

## Considered Options

1. **In-Memory Request Queue / Concurrency Semaphore:**
   - Use Python's `asyncio.Semaphore(1)` within the FastAPI app.
   - *Rejected:* Multi-worker Uvicorn setups run isolated memory spaces. Worker 1 has no visibility into Worker 2's semaphore. Furthermore, queuing forces users 2–20 to wait several seconds for User 1 to finish, resulting in perceived unresponsiveness.

2. **Pure Cloud Routing (Gemini Only):**
   - Route all multi-user traffic directly to Google Gemini.
   - *Rejected:* Completely negates the architectural value and portfolio demonstration of self-hosting a modern 35B open-source model on Apple Silicon hardware.

3. **Distributed Atomic Redis Concurrency Lease with Instant Cloud Overflow (Chosen):**
   - Use the existing Redis instance on Lightsail to track in-flight generation on the local model using an atomic key lease (`llm:qwen:busy`).
   - When a request arrives, the backend attempts to acquire the lease. If acquired, the request streams from the local M5 model.
   - If the lease is already held by another in-flight request, the incoming query **immediately overflows to Google Gemini with zero wait time**.
   - Upon completion (or failure), the lease is deleted in a `finally` block, freeing the local model for the very next request.

## Decision

We adopt **Option 3: Distributed Atomic Redis Concurrency Lease with Instant Cloud Overflow**.

### Concurrency Contract:
1. **Acquire Lease:** `redis.set("llm:qwen:busy", "1", nx=True, ex=45)`
   - `nx=True`: Guarantees atomic, race-safe acquisition across all Uvicorn worker processes.
   - `ex=45`: Failsafe TTL prevents permanent deadlocks if a worker dies abruptly or the tunnel drops mid-stream.
2. **Dynamic Dispatching:**
   - If acquired: stream via `ChatOpenAI` targeting `LOCAL_LLM_BASE_URL`.
   - If denied (already busy): immediately stream via `ChatGoogleGenerativeAI` (`gemini-3.8-flash`).
3. **Release Lease:** `redis.delete("llm:qwen:busy")` executed unconditionally inside a `finally` block when token generation finishes or aborts.
4. **Decoupled Agent Binding:** Remove static module-level model singletons in `backend/agent/bot.py` and `backend/agent/sub_agents/item_agent.py` to allow dynamic model selection per request turn.

## Consequences

- **Positive:**
  - **Optimal Throughput:** Exactly 1 user receives lightning-fast local Apple M5 generation (~50–70 t/s); users 2–20 receive instant Gemini 3.8 Flash responses (~80–100 t/s) with 0ms queuing latency.
  - **Laptop Safety:** The M5 MacBook Pro never exceeds single-stream GPU/memory load, eliminating fan noise, thermal throttling, and memory swapping.
  - **Portfolio Story:** Serves as a prime demonstration of hybrid cloud-edge architecture, graceful degradation, and distributed concurrency control.
- **Negative:**
  - In a multi-turn conversation, a buyer might receive Turn 1 from Qwen and Turn 2 from Gemini if another user triggered Qwen in between. However, because both models share the exact same `SELLER_PERSONA` and conversation history, stylistic divergence is minimal.
