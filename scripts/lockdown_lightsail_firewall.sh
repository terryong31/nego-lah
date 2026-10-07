#!/usr/bin/env bash
# ==============================================================================
# AWS Lightsail & Host Firewall Lockdown to Cloudflare IP Ranges (SPEC-077 / ADR-0025)
#
# Closes direct origin access on ports 80 and 443 so traffic to api.negolah.my
# MUST route through Cloudflare Edge (where WAF, DDoS protection, and rate limits apply).
#
# This alone is NOT enough: Cloudflare's ranges are shared by every tenant, so
# another account's zone can still reach the origin. Caddy closes that gap by
# requiring the X-Origin-Auth header our zone adds (ADR-0032, SPEC-104).
#
# IMPORTANT:
# - Do NOT hardcode the literal Lightsail public IP in this repository.
# - Port 22 (SSH) should remain restricted to your administration IP/VPN.
# ==============================================================================

set -euo pipefail

echo "==> Fetching authoritative Cloudflare IP ranges..."
CF_IPV4=$(curl -sS https://www.cloudflare.com/ips-v4)
CF_IPV6=$(curl -sS https://www.cloudflare.com/ips-v6)

echo "Fetched $(echo "$CF_IPV4" | wc -l | tr -d ' ') IPv4 ranges and $(echo "$CF_IPV6" | wc -l | tr -d ' ') IPv6 ranges."

INSTANCE_NAME="${1:-nego-lah-api}"
REGION="${AWS_DEFAULT_REGION:-ap-southeast-1}"

echo ""
echo "=== Option A: AWS CLI (Lightsail Instance Firewall) ==="
echo "To lock down AWS Lightsail instance '${INSTANCE_NAME}' in region '${REGION}':"
echo ""

# Build cidr list for AWS CLI JSON payload
CIDRS=()
for ip in $CF_IPV4; do
  CIDRS+=("\"$ip\"")
done

CIDR_JOINED=$(IFS=,; echo "${CIDRS[*]}")

cat <<EOF
Run the following AWS CLI command to configure port 443 on Lightsail:

aws lightsail put-instance-public-ports \\
  --region "${REGION}" \\
  --instance-name "${INSTANCE_NAME}" \\
  --port-infos '[
    {
      "fromPort": 443,
      "toPort": 443,
      "protocol": "tcp",
      "cidrs": [${CIDR_JOINED}]
    },
    {
      "fromPort": 80,
      "toPort": 80,
      "protocol": "tcp",
      "cidrs": [${CIDR_JOINED}]
    }
  ]'

EOF

echo "=== Option B: Host-Level UFW (Run inside Lightsail Ubuntu instance) ==="
cat << 'EOF'
If configuring host-level UFW inside the Lightsail VM:

# Reset/Allow SSH first
sudo ufw allow 22/tcp

# Delete broad HTTP/HTTPS rules
sudo ufw delete allow 80/tcp || true
sudo ufw delete allow 443/tcp || true

# Allow Cloudflare IPv4 ranges
for ip in $(curl -sS https://www.cloudflare.com/ips-v4); do
  sudo ufw allow from "$ip" to any port 80 proto tcp
  sudo ufw allow from "$ip" to any port 443 proto tcp
done

# Allow Cloudflare IPv6 ranges
for ip in $(curl -sS https://www.cloudflare.com/ips-v6); do
  sudo ufw allow from "$ip" to any port 80 proto tcp
  sudo ufw allow from "$ip" to any port 443 proto tcp
done

sudo ufw reload
sudo ufw status verbose
EOF

echo ""
echo "==> Done. Verify with: curl -I https://api.negolah.my/health"
