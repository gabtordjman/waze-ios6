#!/bin/sh
# Regénère mitm/certs/tls avec WAZE_SERVER_IP dans le SAN.
set -e
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TLS="$ROOT/mitm/certs/tls"
IP="${WAZE_SERVER_IP:-${PC_IP:-$(hostname -I 2>/dev/null | awk '{print $1}')}}"
IP="${IP:-127.0.0.1}"

cat > "$TLS/san.cnf" << EOF
[ req ]
default_bits = 2048
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[ dn ]
CN = waze.local

[ req_ext ]
subjectAltName = @alt_names

[ alt_names ]
DNS.1 = rt.waze.com
DNS.2 = www.waze.com
DNS.3 = waze.com
DNS.4 = tiles.waze.com
IP.1 = $IP
EOF

cd "$TLS"
openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout leaf.key -out leaf.crt -days 825 \
  -config san.cnf -extensions req_ext
cp leaf.crt leaf-chain.crt
echo "OK TLS SAN IP=$IP → $TLS/leaf-chain.crt"
