# 2. Modular Monolith over Distributed gRPC Microservices

- Status: Accepted
- Date: 2026-09-04
- Deciders: Terry (owner), AI Agent

## Context

As the platform evolved to support autonomous negotiations, image analysis, and administration, we considered breaking the backend into microservices communicating over gRPC.

The deployment target is an **AWS Lightsail instance (2 GB RAM, 1-2 vCPUs)** behind a Caddy reverse proxy.

### Decision Drivers

- **Memory Constraints:** Running multiple Python processes, gRPC servers, and auxiliary containers would quickly exceed 2 GB RAM, leading to kernel OOM killing.
- **Browser Compatibility:** Web browsers cannot speak native HTTP/2 gRPC without gRPC-Web proxies (e.g., Envoy), adding another moving piece.
- **Operational Simplicity:** A single modular process requires zero distributed tracing, service meshes, or complex multi-service deployment orchestrations.
- **Development Velocity:** In-process domain communication avoids network serialization overhead and network failure modes.

## Considered Options

1. **Distributed gRPC Microservices:** Partition into separate services (Catalog, Negotiation, Billing, Identity) with protobuf definitions and internal gRPC channels.
2. **Modular Monolith:** Retain a single FastAPI application process, strictly partitioned into internal bounded domains (`domains/catalog`, `domains/negotiation`, `domains/billing`, `domains/identity`, `domains/webhooks`) with clear Domain Service interfaces and shared infrastructure (`core/`).

## Decision

We chose **Option 2: Modular Monolith**.

- Business logic is partitioned into `backend/domains/` with strict domain boundaries.
- Cross-domain interactions occur through explicit exported service contracts (`CatalogService`, `BillingService`) rather than direct database table access.
- Shared infrastructure lives in `backend/core/` (`config.py`, `database.py`, `security.py`, `telemetry.py`).
- Single deployment artifact running on AWS Lightsail behind Caddy.

## Consequences

- **Positive:** Low memory footprint (<250 MB RSS), fast test execution (880 tests in ~5s), zero inter-service network latency, simple CI/CD deployment.
- **Negative:** Independent scaling of individual subdomains is not possible without splitting, though unnecessary given current transaction volumes.
