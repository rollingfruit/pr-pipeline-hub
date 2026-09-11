# HTTP demonstration only: passwords and requests are not encrypted.
# Include inside the existing 8080 server; do not replace historical routes.
location = /submit { return 302 /submit/; }
location /submit/ {
    allow 127.0.0.1;
    allow ::1;
    allow 124.70.231.102/32;
    # Verified local Palantir proxy egress; login remains mandatory.
    allow 23.185.208.12/32;
    # Additional team egress observed in the reported /submit/ denials.
    allow 14.137.135.22/32;
    deny all;
    client_max_body_size 64k;
    proxy_pass http://127.0.0.1:8793/;
    proxy_set_header Host $http_host;
    proxy_set_header Authorization $http_authorization;
    proxy_read_timeout 300s;
    add_header Cache-Control "no-store" always;
    add_header Referrer-Policy "no-referrer" always;
}
