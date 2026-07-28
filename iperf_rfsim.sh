#!/usr/bin/env bash
# Simple, configurable iperf3 throughput test for the RFsim oai-gnb + oai-nr-ue setup.
#
# Runs the iperf3 server locally (bound to the Open5GS UPF gateway, 10.45.0.1 by
# default) and drives the client from inside the oai-nr-ue pod via `kubectl exec`,
# same pattern as the manual test that validated 10.45.0.x <-> 10.45.0.1 connectivity.
#
# Usage:
#   ./iperf_rfsim.sh [-p tcp|udp] [-d ul|dl|both] [-b BANDWIDTH] [-t SECONDS] [-i SECONDS]
#
#   -p  protocol: tcp (default) or udp
#   -d  direction: ul (UE->server), dl (server->UE, -R), or both (default)
#   -b  target bandwidth for -c client, e.g. "50M" (udp: sets -b; tcp: sets -b if given, else unlimited)
#   -t  test duration in seconds (default 10)
#   -i  report interval in seconds (default 2)
#   -n  kubernetes namespace (default ming-ns)
#   -s  iperf3 server bind IP / UPF gateway (default 10.45.0.1)
#
# Examples:
#   ./iperf_rfsim.sh                          # TCP, both directions, 10s
#   ./iperf_rfsim.sh -p udp -b 20M -d dl       # UDP downlink @ 20 Mbps target
#   ./iperf_rfsim.sh -p tcp -d ul -t 20        # TCP uplink, 20s

set -euo pipefail

KUBECONFIG_PATH="/home/hpe/CRAN/ming-kubeconfig.yaml"
KUBECTL="/home/hpe/CRAN/kubectl"
NAMESPACE="ming-ns"
UE_LABEL="app.kubernetes.io/name=oai-nr-ue"
SERVER_IP="10.45.0.1"

PROTO="tcp"
DIRECTION="both"
BANDWIDTH=""
DURATION=10
INTERVAL=2

usage() {
    local exit_code="${1:-1}"
    grep '^#' "$0" | sed -n '2,/^set -euo/p' | sed '$d' | sed 's/^# \{0,1\}//'
    exit "$exit_code"
}

while getopts "p:d:b:t:i:n:s:h" opt; do
    case "$opt" in
        p) PROTO="$OPTARG" ;;
        d) DIRECTION="$OPTARG" ;;
        b) BANDWIDTH="$OPTARG" ;;
        t) DURATION="$OPTARG" ;;
        i) INTERVAL="$OPTARG" ;;
        n) NAMESPACE="$OPTARG" ;;
        s) SERVER_IP="$OPTARG" ;;
        h) usage 0 ;;
        *) usage 1 ;;
    esac
done

if [[ "$PROTO" != "tcp" && "$PROTO" != "udp" ]]; then
    echo "[ERROR] -p must be tcp or udp, got: $PROTO" >&2
    exit 1
fi
if [[ "$DIRECTION" != "ul" && "$DIRECTION" != "dl" && "$DIRECTION" != "both" ]]; then
    echo "[ERROR] -d must be ul, dl, or both, got: $DIRECTION" >&2
    exit 1
fi

KCTL=("$KUBECTL" "--kubeconfig=$KUBECONFIG_PATH" "-n" "$NAMESPACE")

find_ue_pod() {
    "${KCTL[@]}" get pods -l "$UE_LABEL" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

get_ue_ip() {
    local pod="$1"
    "${KCTL[@]}" exec "$pod" -c nr-ue -- sh -c \
        "ifconfig oaitun_ue1 2>/dev/null | grep -oE 'inet [0-9.]+' | awk '{print \$2}'"
}

SERVER_PID=""
cleanup() {
    if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
    sudo pkill -9 iperf3 2>/dev/null || true
}
trap cleanup EXIT

echo "[1/4] Locating oai-nr-ue pod in namespace $NAMESPACE..."
UE_POD="$(find_ue_pod)"
if [[ -z "$UE_POD" ]]; then
    echo "[ERROR] No pod found matching -l $UE_LABEL in namespace $NAMESPACE. Is it deployed?" >&2
    exit 1
fi
echo "   > UE pod: $UE_POD"

echo "[2/4] Reading UE tunnel IP (oaitun_ue1)..."
UE_IP="$(get_ue_ip "$UE_POD")"
if [[ -z "$UE_IP" ]]; then
    echo "[ERROR] UE has no oaitun_ue1 IP. PDU session may not be established." >&2
    exit 1
fi
echo "   > UE IP: $UE_IP"

echo "[3/4] Starting local iperf3 server bound to $SERVER_IP..."
sudo pkill -9 iperf3 2>/dev/null || true
sleep 1
iperf3 -s -B "$SERVER_IP" >/tmp/iperf_rfsim_server.log 2>&1 &
SERVER_PID=$!
sleep 1
if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "[ERROR] iperf3 server failed to start. Log:" >&2
    cat /tmp/iperf_rfsim_server.log >&2
    exit 1
fi
echo "   > Server PID: $SERVER_PID"

run_client() {
    local dir_label="$1"
    shift
    local extra_args=("$@")

    echo
    echo "=== [$PROTO/$dir_label] duration=${DURATION}s interval=${INTERVAL}s${BANDWIDTH:+ bandwidth=$BANDWIDTH} ==="
    "${KCTL[@]}" exec "$UE_POD" -c nr-ue -- \
        iperf3 -c "$SERVER_IP" -B "$UE_IP" -t "$DURATION" -i "$INTERVAL" "${extra_args[@]}"
}

echo "[4/4] Running test(s)..."
COMMON_ARGS=()
[[ "$PROTO" == "udp" ]] && COMMON_ARGS+=(-u)
[[ -n "$BANDWIDTH" ]] && COMMON_ARGS+=(-b "$BANDWIDTH")

if [[ "$DIRECTION" == "ul" || "$DIRECTION" == "both" ]]; then
    run_client "uplink (UE->server)" "${COMMON_ARGS[@]}"
fi
if [[ "$DIRECTION" == "dl" || "$DIRECTION" == "both" ]]; then
    run_client "downlink (server->UE)" "${COMMON_ARGS[@]}" -R
fi

echo
echo "[DONE] All requested tests completed."
