#!/usr/bin/env bash
# ==============================================================================
# Turn on (or rotate) the origin secret header — ADR-0032 / SPEC-104.
#
#   1. Refuses unless api.negolah.my is Proxied (orange cloud). A DNS-only
#      record sends requests straight to Caddy, so no rule ever adds the header.
#   2. Puts ORIGIN_AUTH_SECRET in Infisical prod:/Backend (generated if absent).
#   3. Creates or updates the Cloudflare Transform Rule that adds X-Origin-Auth
#      to every request for api.negolah.my. Other rules in that phase are kept.
#   4. Checks the API still answers through the edge (cf-ray present).
#
# Caddy starts enforcing on the next backend deploy. The deploy itself refuses
# to leave enforcement on if the edge gets a 403, so running this late is safe;
# running it early is harmless.
#
# Needs: infisical (logged in), curl, jq, openssl, and CLOUDFLARE_API_TOKEN with
#   Zone → Transform Rules → Edit,   Zone → Zone → Read   and   Zone → DNS → Read,
#   for negolah.my.
#
# Usage:  CLOUDFLARE_API_TOKEN=... scripts/enable_origin_auth.sh [--rotate]
#   --rotate  issue a new secret. Requests 403 from the moment Cloudflare has it
#             until the redeploy finishes, so redeploy straight after.
#
# The secret is never printed.
# ==============================================================================

set -euo pipefail

ZONE_NAME="negolah.my"
HOST="api.negolah.my"
RULE_REF="negolah_origin_auth"
PHASE="http_request_late_transform"
INFISICAL_ARGS=(--env=prod --path=/Backend)
API="https://api.cloudflare.com/client/v4"

: "${CLOUDFLARE_API_TOKEN:?set CLOUDFLARE_API_TOKEN (Transform Rules: Edit, Zone: Read, DNS: Read)}"
ROTATE=0
[ "${1:-}" = "--rotate" ] && ROTATE=1

cf() {
  curl -sS -H "Authorization: Bearer ${CLOUDFLARE_API_TOKEN}" -H "Content-Type: application/json" "$@"
}

echo "==> Looking up zone ${ZONE_NAME}"
ZONE_ID=$(cf "${API}/zones?name=${ZONE_NAME}" | jq -r '.result[0].id // empty')
if [ -z "$ZONE_ID" ]; then
  echo "The token cannot see ${ZONE_NAME}. Edit it in the Cloudflare dashboard:" >&2
  echo "  Permissions:    Zone → Zone → Read,  Zone → Transform Rules → Edit,  Zone → DNS → Read" >&2
  echo "  Zone Resources: Include → Specific zone → ${ZONE_NAME}" >&2
  exit 1
fi

echo "==> Checking ${HOST} is proxied"
DNS=$(cf "${API}/zones/${ZONE_ID}/dns_records?name=${HOST}")
if [ "$(jq -r '.success' <<<"$DNS")" != "true" ]; then
  echo "Cloudflare would not list the DNS records. Add Zone → DNS → Read to the token." >&2
  exit 1
fi
RECORDS=$(jq '[.result[] | select(.type == "A" or .type == "AAAA" or .type == "CNAME")]' <<<"$DNS")
if [ "$(jq 'length' <<<"$RECORDS")" = 0 ]; then
  echo "${ZONE_NAME} has no A, AAAA or CNAME record for ${HOST}." >&2
  exit 1
fi
if [ "$(jq 'all(.proxied == true)' <<<"$RECORDS")" != "true" ]; then
  echo "${HOST} is DNS-only: requests reach Caddy without crossing the zone, so the" >&2
  echo "rule would never add the header and enforcement would refuse everything." >&2
  echo "In Cloudflare → DNS, set the ${HOST} record to Proxied (orange cloud), with" >&2
  echo "SSL/TLS on Full (strict), then run this again." >&2
  exit 1
fi

echo "==> Resolving the secret"
SECRET=""
if [ "$ROTATE" = 0 ]; then
  SECRET=$(infisical secrets get ORIGIN_AUTH_SECRET "${INFISICAL_ARGS[@]}" --plain --silent 2>/dev/null || true)
fi
if [ -z "$SECRET" ]; then
  SECRET=$(openssl rand -hex 32)
  echo "    generated a new one"
else
  echo "    reusing the one in Infisical"
fi

echo "==> Writing the Transform Rule"
ENTRY=$(cf "${API}/zones/${ZONE_ID}/rulesets/phases/${PHASE}/entrypoint")
if [ "$(jq -r '.success' <<<"$ENTRY")" = "true" ]; then
  EXISTING=$(jq '[.result.rules // [] | .[] | select(.ref != $ref) | del(.version, .last_updated)]' \
    --arg ref "$RULE_REF" <<<"$ENTRY")
else
  EXISTING='[]'   # phase has no entrypoint yet; the PUT creates it
fi
BODY=$(jq -n --argjson existing "$EXISTING" --arg ref "$RULE_REF" --arg host "$HOST" --arg secret "$SECRET" '{
  rules: ($existing + [{
    ref: $ref,
    description: "ADR-0032: X-Origin-Auth proves the request came through this zone",
    expression: ("(http.host eq \"" + $host + "\")"),
    action: "rewrite",
    action_parameters: { headers: { "X-Origin-Auth": { operation: "set", value: $secret } } },
    enabled: true
  }])
}')
RESULT=$(cf -X PUT "${API}/zones/${ZONE_ID}/rulesets/phases/${PHASE}/entrypoint" --data "$BODY")
if [ "$(jq -r '.success' <<<"$RESULT")" != "true" ]; then
  echo "Cloudflare refused the rule:" >&2
  jq -c '.errors' <<<"$RESULT" >&2
  exit 1
fi
echo "    rule '${RULE_REF}' in place ($(jq '.result.rules | length' <<<"$RESULT") rule(s) in the phase)"

echo "==> Storing the secret in Infisical prod:/Backend"
infisical secrets set "ORIGIN_AUTH_SECRET=${SECRET}" "${INFISICAL_ARGS[@]}" --silent >/dev/null

echo "==> Checking the API through the edge"
HDRS=$(mktemp)
CODE=$(curl -s -o /dev/null -D "$HDRS" -w '%{http_code}' --max-time 15 "https://${HOST}/health" || true)
RAY=$(grep -i '^cf-ray:' "$HDRS" | cut -d: -f2 | tr -d ' \r' || true)
rm -f "$HDRS"
echo "    https://${HOST}/health -> ${CODE}${RAY:+ (cf-ray ${RAY})}"
if [ -z "$RAY" ]; then
  # The record is proxied, so this machine resolves the host some other way.
  echo "That response did not pass through Cloudflare (no cf-ray). Check /etc/hosts" >&2
  echo "and any local DNS override for ${HOST}, then probe again." >&2
  exit 1
fi

echo ""
echo "Done. Enforcement starts on the next backend deploy (merge, or re-run the"
echo "deploy job). Then confirm a request that skips Cloudflare is refused:"
echo "  curl -sk -o /dev/null -w '%{http_code}\\n' --resolve ${HOST}:443:<origin IP> https://${HOST}/health   # expect 403"
