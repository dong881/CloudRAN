#!/usr/bin/env python3
import sys
import os
import time
import subprocess
import json
import re
from datetime import datetime

# Import the unified UE driver
sys.path.append("/home/hpe/ming-logs")
from ue_driver import make_ue_driver

KUBECONFIG = "/home/hpe/CRAN/ming-kubeconfig.yaml"
KUBECTL = "/home/hpe/CRAN/kubectl"
NAMESPACE = "ming-ns"

def run_cmd(cmd, timeout=15):
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return res
    except subprocess.TimeoutExpired:
        print(f"[WARNING] Command timed out: {cmd}")
        return None

def check_k8s_pods():
    print("[1/6] Checking VNF and PNF pods on O-Cloud cluster...")
    cmd = [KUBECTL, f"--kubeconfig={KUBECONFIG}", "get", "pods", "-n", NAMESPACE, "-o", "json"]
    res = run_cmd(cmd)
    if not res or res.returncode != 0:
        print(f"[ERROR] Failed to query pods in namespace {NAMESPACE}: {res.stderr if res else 'timeout'}")
        return False
        
    try:
        data = json.loads(res.stdout)
        vnf_ok = False
        pnf_ok = False
        for item in data.get("items", []):
            name = item["metadata"]["name"]
            status = item["status"]["phase"]
            # Check container readiness
            container_statuses = item["status"].get("containerStatuses", [])
            ready = all(cs.get("ready", False) for cs in container_statuses) if container_statuses else False
            
            if "oai-vnf" in name and status == "Running" and ready:
                print(f"   > VNF Pod: {name} is Running & Ready")
                vnf_ok = True
            elif "oai-pnf" in name and status == "Running" and ready:
                print(f"   > PNF Pod: {name} is Running & Ready")
                pnf_ok = True
                
        if vnf_ok and pnf_ok:
            print("[SUCCESS] Both VNF and PNF pods are Running and Ready!")
            return True
        else:
            print("[ERROR] Pods are not fully ready. Please check 'kubectl get pods -n ming-ns'")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to parse pods json: {e}")
        return False

def main():
    # 1. Check K8s Pods status
    if not check_k8s_pods():
        sys.exit(1)
        
    # 2. Make UE Driver and bring UE online
    print("[2/6] Initializing Samsung UE (R5CN30TMBYR)...")
    try:
        driver = make_ue_driver("samsung")
    except Exception as e:
        print(f"[ERROR] Failed to load Samsung UE driver: {e}")
        sys.exit(1)
        
    print("   > Ensuring UE is online and has obtained 10.45.x.x IP...")
    if not driver.ensure_online(timeout=120):
        print("[ERROR] Failed to bring UE online. IP not obtained.")
        sys.exit(1)
        
    ue_ip = driver.get_ip()
    print(f"[SUCCESS] UE is online with IP: {ue_ip}")
    
    # 3. Start local iperf3 server on UPF (ogstun: 10.45.0.1)
    print("[3/6] Starting iperf3 server locally on ogstun (10.45.0.1)...")
    # Kill any existing iperf3 server first
    subprocess.run(["sudo", "pkill", "-9", "iperf3"], capture_output=True)
    time.sleep(1)
    
    # Start iperf3 server locally, binding to 10.45.0.1
    iperf_srv = subprocess.Popen(
        ["iperf3", "-s", "-B", "10.45.0.1", "-1"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    time.sleep(2)
    
    # 4. Trigger iperf client on UE
    print("[4/6] Starting 500Mbps Downlink iperf test from UE (10s duration)...")
    iperf_proc = driver.start_iperf_client(
        bandwidth_list=[500],
        period=10,
        gap_time=2,
        uplink=False
    )
    
    # Monitor iperf output
    os.set_blocking(iperf_proc.stdout.fileno(), False)
    while True:
        try:
            line = iperf_proc.stdout.readline()
            if line:
                print(f"[UE IPERF] {line.strip()}", flush=True)
        except Exception:
            pass
            
        if iperf_proc.poll() is not None:
            print("[INFO] UE iperf execution completed.")
            break
        time.sleep(0.5)
        
    # Wait for local iperf server to dump output and finish
    iperf_srv_out, iperf_srv_err = iperf_srv.communicate(timeout=5)
    print("\n--- Local iperf3 Server JSON Output ---")
    try:
        srv_json = json.loads(iperf_srv_out)
        sum_rx = srv_json["end"]["sum_received"]
        bits_per_sec = sum_rx["bits_per_second"]
        mbytes = sum_rx["bytes"] / (1024 * 1024)
        print(f"Achieved Throughput: {bits_per_sec / 1e6:.2f} Mbps")
        print(f"Total Bytes Transferred: {mbytes:.2f} MBytes")
        print(f"Jitter: {sum_rx.get('jitter_ms', 0):.3f} ms")
        print(f"Packet Loss: {sum_rx.get('lost_percent', 0):.2f}%")
        print("[SUCCESS] End-to-End data transfer verified successfully!")
    except Exception as e:
        print("[WARNING] Failed to parse local iperf server json output. Raw output:")
        print(iperf_srv_out)
        print(iperf_srv_err)
        
    # 5. Collect Logs
    print("\n[5/6] Collecting logs from VNF and PNF pods...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_dir = f"logs_e2e_{timestamp}"
    os.makedirs(log_dir, exist_ok=True)
    
    vnf_log_file = os.path.join(log_dir, "vnf_pod.log")
    pnf_log_file = os.path.join(log_dir, "pnf_pod.log")
    
    print(f"   > Writing VNF logs to {vnf_log_file}...")
    subprocess.run(
        f"{KUBECTL} --kubeconfig={KUBECONFIG} logs -n {NAMESPACE} deploy/oai-vnf > {vnf_log_file}",
        shell=True
    )
    
    print(f"   > Writing PNF logs to {pnf_log_file}...")
    subprocess.run(
        f"{KUBECTL} --kubeconfig={KUBECONFIG} logs -n {NAMESPACE} deploy/oai-pnf-pegatron > {pnf_log_file}",
        shell=True
    )
    
    # 6. Put UE back to Airplane mode
    print("\n[6/6] Toggling Airplane Mode ON to save UE battery...")
    driver.airplane("on")
    print(f"[FINISHED] All steps completed! Logs are saved in directory: {log_dir}")

if __name__ == "__main__":
    main()
