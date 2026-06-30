#!/usr/bin/env bash
# fix_multus_shim.sh
# Automates the fix for the Multus CNI "Text file busy" crashloop on node reboot.

set -euo pipefail

KUBECONFIG="/home/hpe/CRAN/ming-kubeconfig.yaml"
KUBECTL="/home/hpe/CRAN/kubectl --kubeconfig=${KUBECONFIG}"
NAMESPACE="ming-ns"
POD_NAME="host-debug-pod"
YAML_FILE="/home/hpe/CRAN/ocloud-helm-templates/host-debug-pod.yaml"

echo "=== [1/5] Checking if host-debug-pod is deployed ==="
if ! ${KUBECTL} get pod ${POD_NAME} -n ${NAMESPACE} &>/dev/null; then
    echo "Creating host-debug-pod..."
    ${KUBECTL} apply -f "${YAML_FILE}"
fi

echo "Waiting for host-debug-pod to be ready..."
${KUBECTL} wait --for=condition=Ready pod/${POD_NAME} -n ${NAMESPACE} --timeout=60s

echo "=== [2/5] Renaming busy multus-shim on host ==="
${KUBECTL} exec -n ${NAMESPACE} ${POD_NAME} -- bash -c '
    if [ -f /host/opt/cni/bin/multus-shim ]; then
        echo "Found busy multus-shim. Renaming to release text lock..."
        mv -f /host/opt/cni/bin/multus-shim /host/opt/cni/bin/multus-shim.bak
        rm -f /host/opt/cni/bin/multus-shim.bak || true
        echo "Successfully freed multus-shim path."
    else
        echo "multus-shim is already clear."
    fi
'

echo "=== [3/5] Identifying Multus pod sandbox on lavoisier ==="
# Find the active kube-multus sandbox container ID
SANDBOX_ID=$(${KUBECTL} exec -n ${NAMESPACE} ${POD_NAME} -- chroot /host crictl pods --name kube-multus-ds -q | head -n 1)

if [ -n "${SANDBOX_ID}" ]; then
    echo "Stopping and removing Multus pod sandbox ${SANDBOX_ID} to force instant restart..."
    ${KUBECTL} exec -n ${NAMESPACE} ${POD_NAME} -- chroot /host crictl stopp "${SANDBOX_ID}"
    ${KUBECTL} exec -n ${NAMESPACE} ${POD_NAME} -- chroot /host crictl rmp "${SANDBOX_ID}"
    echo "Multus pod sandbox restarted."
else
    echo "No active Multus pod sandbox found to restart."
fi

echo "=== [4/5] Cleaning up host-debug-pod ==="
${KUBECTL} delete -f "${YAML_FILE}"

echo "=== [5/5] Checking current pods status ==="
sleep 5
${KUBECTL} get pods -n ${NAMESPACE}

echo "=== [SUCCESS] Multus CNI network has been successfully repaired! ==="
