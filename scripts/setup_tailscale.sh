#!/usr/bin/env bash
set -euo pipefail

# SignalDeck Tailscale VPN setup
# Provides secure remote access without port forwarding

echo "=== SignalDeck Tailscale Setup ==="

# Check if Tailscale is installed
if ! which tailscale &>/dev/null; then
    echo "Installing Tailscale..."
    curl -fsSL https://tailscale.com/install.sh | sh
fi

# Check status
echo ""
echo "Tailscale status:"
sudo tailscale status 2>/dev/null || echo "  Not connected"

# Connect if not already
if ! sudo tailscale status &>/dev/null; then
    echo ""
    echo "Starting Tailscale..."
    echo "You'll need to authenticate via the URL shown below:"
    echo ""
    sudo tailscale up
fi

echo ""
echo "=== Tailscale Setup Complete ==="
echo ""

# Show the Tailscale IP
TAILSCALE_IP=$(tailscale ip -4 2>/dev/null || echo "unknown")
echo "Your Tailscale IP: ${TAILSCALE_IP}"
echo ""
echo "Access SignalDeck from any device on your Tailnet:"
echo "  http://${TAILSCALE_IP}:8080"
echo ""
echo "To access from your phone:"
echo "  1. Install Tailscale on your phone"
echo "  2. Sign in with the same account"
echo "  3. Open http://${TAILSCALE_IP}:8080 in your mobile browser"
echo ""
echo "Optional: Enable Tailscale HTTPS (requires MagicDNS):"
echo "  sudo tailscale cert \$(hostname)"
echo "  Then configure SignalDeck to use the cert"
