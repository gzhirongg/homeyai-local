#!/usr/bin/env bash
# Open HTTP/HTTPS on the Oracle VM OS firewall (firewalld).
# Also add matching ingress rules in Oracle Cloud Console:
#   VCN → Subnet → Security List → Ingress: TCP 80 and 443 from 0.0.0.0/0
set -euo pipefail

if ! command -v firewall-cmd >/dev/null 2>&1; then
  echo "firewall-cmd not found. Install firewalld or open ports 80/443 manually." >&2
  exit 1
fi

echo "Opening HTTP (80) and HTTPS (443) in firewalld..."
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

echo "Current permanent services:"
sudo firewall-cmd --permanent --list-services

echo ""
echo "Done. Ensure Oracle Cloud Security List also allows TCP 80 and 443 from 0.0.0.0/0."
