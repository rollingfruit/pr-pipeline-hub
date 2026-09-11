#!/usr/bin/env bash
set -euo pipefail
if ! ip link show e2ebr0 >/dev/null 2>&1; then
  ip link add e2ebr0 type bridge
  ip address add 172.30.250.1/24 dev e2ebr0
fi
ip -4 address show dev e2ebr0 | grep -q '172.30.250.1/24'
ip link set e2ebr0 up
# Keep the default Docker daemon's chains untouched; add only E2E source rules.
for subnet in 172.30.250.0/24 172.29.0.0/16; do
  iptables -t nat -C POSTROUTING -s "$subnet" ! -d "$subnet" -m comment --comment pr-e2e -j MASQUERADE 2>/dev/null ||
    iptables -t nat -A POSTROUTING -s "$subnet" ! -d "$subnet" -m comment --comment pr-e2e -j MASQUERADE
  iptables -C FORWARD -s "$subnet" -m comment --comment pr-e2e -j ACCEPT 2>/dev/null ||
    iptables -I FORWARD -s "$subnet" -m comment --comment pr-e2e -j ACCEPT
  iptables -C FORWARD -d "$subnet" -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment pr-e2e -j ACCEPT 2>/dev/null ||
    iptables -I FORWARD -d "$subnet" -m conntrack --ctstate ESTABLISHED,RELATED -m comment --comment pr-e2e -j ACCEPT
done
