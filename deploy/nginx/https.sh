#!/bin/sh
set -eu

# Generate only the listener; keep every proxy route in the shared HTTP config.
sed 's/listen 80;/listen 443 ssl;\n    ssl_certificate \/certificates\/server.pem;\n    ssl_certificate_key \/certificates\/server.pem;\n    ssl_protocols TLSv1.2 TLSv1.3;/' \
    /etc/nginx/http.conf > /etc/nginx/conf.d/default.conf
cat >> /etc/nginx/conf.d/default.conf <<'EOF'
server {
    listen 80;
    server_name _;
    server_tokens off;
    return 308 https://$host$request_uri;
}
EOF
nginx -t
(
    previous=$(cksum /certificates/server.pem)
    while sleep 60; do
        current=$(cksum /certificates/server.pem)
        if [ "$current" != "$previous" ]; then
            if nginx -t && nginx -s reload; then previous=$current; fi
        fi
    done
) &
exec nginx -g 'daemon off;'
