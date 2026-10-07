# ADR-0032: The origin authenticates our Cloudflare zone with a secret header

- Status: Accepted
- Date: 2026-10-07
- Relates to: SPEC-104; amends ADR-0025 (origin lockdown)

## Context

ADR-0025 restricted the Lightsail firewall to Cloudflare's published IP ranges so traffic must
pass the edge. Those ranges are shared by every Cloudflare customer. Anyone can add a zone, point
a record at our origin IP and send requests to it from Cloudflare addresses; the firewall and
Caddy accept them, and none of `negolah.my`'s WAF, rate-limit or Turnstile rules ran. The same
path let a caller choose its own `CF-Connecting-IP`, which keys every IP rate limit.

The box is a 2 GB Lightsail instance running Caddy and the API under Docker Compose, deployed by
CI. The owner manages Cloudflare by hand.

## Considered options

1. **Zone-level Authenticated Origin Pulls** — Caddy requires Cloudflare's client cert. Loses:
   with Cloudflare's certificate it is the same cert for every customer, so it proves "came from
   Cloudflare", which the firewall already did.
2. **Per-hostname AOP with our own client certificate** — sound, but means running a private CA,
   uploading the leaf through the API and rotating it before expiry. More moving parts than the
   threat needs on a one-person project.
3. **Cloudflare Tunnel** — closes 80/443 entirely. Strongest, but adds a `cloudflared` process to a
   memory-capped box, moves TLS termination and changes DNS. A bigger change than the gap.
4. **Secret request header set by a zone Transform Rule** — only our zone adds it; Caddy rejects
   requests without it. Free plan, one secret, rotates in two places. Wins.

## Decision

A Cloudflare Transform Rule on `api.negolah.my` sets `X-Origin-Auth` to a random secret held in
Infisical as `ORIGIN_AUTH_SECRET`. Caddy returns 403 when the header does not match and strips it
before proxying. Caddy receives that one variable through `caddy.env`, which the deploy writes,
never the backend's env file. Caddy also derives the client IP from `CF-Connecting-IP` only when
the peer is a Cloudflare range, and overwrites the upstream header with that value.

The check is inert while the secret is empty, so the code can merge before the rule exists.
`scripts/enable_origin_auth.sh` creates the rule and the secret together. If a deploy's request
through the edge is refused by Caddy anyway, it switches the check off and fails red rather than
leave the API down. Caddy marks that refusal (`X-Origin-Check: refused`) because Cloudflare
answers some requests with its own 403, such as a Bot Fight Mode challenge to the server's
datacenter IP. Those never reach the origin and must not switch the check off.

## Consequences

- A request through another tenant's zone, or straight to the IP, gets 403 before the API runs.
- Rotation is `scripts/enable_origin_auth.sh --rotate` and a redeploy, with 403s between the two;
  do it at a quiet hour.
- Until the owner completes the rollout steps in SPEC-104, nothing is enforced. That state is
  invisible from the code, so the rollout is tracked in the spec's acceptance criteria.
- Anyone with Cloudflare dashboard access can read the secret; that is the same trust boundary as
  the zone itself.
