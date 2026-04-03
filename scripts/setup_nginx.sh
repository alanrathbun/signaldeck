#!/usr/bin/env bash
set -euo pipefail

# SignalDeck Nginx reverse proxy setup
# Usage: ./scripts/setup_nginx.sh [--domain example.com] [--https]

DOMAIN=""
HTTPS=false
PORT=8080

while [[ $# -gt 0 ]]; do
    case $1 in
        --domain) DOMAIN="$2"; shift 2 ;;
        --https) HTTPS=true; shift ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

echo "=== SignalDeck Nginx Setup ==="

# Install nginx if not present
if ! which nginx &>/dev/null; then
    echo "Installing nginx..."
    sudo apt-get update -qq
    sudo apt-get install -y -qq nginx
fi

# Generate nginx config
SERVER_NAME="${DOMAIN:-_}"

NGINX_CONF="/etc/nginx/sites-available/signaldeck"

sudo tee "$NGINX_CONF" > /dev/null << NGINX_EOF
# SignalDeck reverse proxy configuration

upstream signaldeck {
    server 127.0.0.1:${PORT};
}

server {
    listen 80;
    server_name ${SERVER_NAME};

    # Security headers
    add_header X-Frame-Options DENY;
    add_header X-Content-Type-Options nosniff;
    add_header X-XSS-Protection "1; mode=block";

    # Proxy settings
    location / {
        proxy_pass http://signaldeck;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }

    # WebSocket support
    location /ws/ {
        proxy_pass http://signaldeck;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_read_timeout 86400;
    }

    # Audio file serving (larger body size for recordings)
    location /api/recordings/ {
        proxy_pass http://signaldeck;
        proxy_set_header Host \$host;
        client_max_body_size 100M;
    }
}
NGINX_EOF

# Enable the site
sudo ln -sf "$NGINX_CONF" /etc/nginx/sites-enabled/signaldeck
sudo rm -f /etc/nginx/sites-enabled/default

# Test and reload
sudo nginx -t
sudo systemctl reload nginx

echo "Nginx configured: http://${DOMAIN:-localhost}"

# Optional HTTPS with Let's Encrypt
if [ "$HTTPS" = true ] && [ -n "$DOMAIN" ]; then
    echo ""
    echo "Setting up HTTPS with Let's Encrypt..."
    if ! which certbot &>/dev/null; then
        sudo apt-get install -y -qq certbot python3-certbot-nginx
    fi
    sudo certbot --nginx -d "$DOMAIN" --non-interactive --agree-tos --email "admin@${DOMAIN}"
    echo "HTTPS configured: https://${DOMAIN}"
fi

echo ""
echo "=== Setup complete ==="
echo "SignalDeck is accessible via Nginx"
