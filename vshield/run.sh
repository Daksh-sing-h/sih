#!/usr/bin/env bash
# Start V-Shield: builds the dashboard if needed, then serves everything.
#
#   ./run.sh         this laptop only      → http://127.0.0.1:8000
#   ./run.sh --lan   other devices on your Wi-Fi can join calls → https://<your-ip>:8443
#                    (browsers only allow the microphone on localhost or HTTPS, so LAN mode
#                    uses a self-signed certificate; click "Advanced → Proceed" once per device)
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d frontend/dist ]; then
  (cd frontend && npm install && npm run build)
fi
cd backend

if [ "${1:-}" = "--lan" ]; then
  IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}')
  if [ -z "$IP" ]; then echo "Couldn't find this laptop's Wi-Fi IP address." >&2; exit 1; fi
  mkdir -p certs
  if [ ! -f "certs/$IP.pem" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=V-Shield demo" \
      -addext "subjectAltName=IP:$IP,IP:127.0.0.1,DNS:localhost" \
      -keyout "certs/$IP.key" -out "certs/$IP.pem" 2>/dev/null
  fi
  echo "V-Shield on your network → https://$IP:8443"
  echo "  Open it on both laptops (same Wi-Fi). The browser warns about the certificate: Advanced → Proceed."
  echo "  Only do this on a network you trust: the server has no login."
  exec .venv/bin/python -m uvicorn vshield.server:app --host 0.0.0.0 --port 8443 \
    --ssl-keyfile "certs/$IP.key" --ssl-certfile "certs/$IP.pem"
fi

echo "V-Shield → http://127.0.0.1:8000  (first start downloads ~2 GB of models)"
exec .venv/bin/python -m uvicorn vshield.server:app --host 127.0.0.1 --port 8000
