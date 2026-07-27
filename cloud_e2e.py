
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime

# Import the unified UE driver
sys.path.append("/home/hpe/ming-logs")
from ue_driver import make_ue_driver  # noqa: E402


KUBECONFIG = "/home/hpe/CRAN/ming-kubeconfig.yaml"
KUBECTL = "/home/hpe/CRAN/kubectl"
NAMESPACE = "ming-ns"


def parse_bandwidths(raw: str) -> list[int]:
    values = [int(item.strip()) for item in raw.split(",") if item.strip()]
    if not values:
        raise argparse.ArgumentTypeError("bandwidth must contain at least one Mbps value")
    if any(value <= 0 for value in values):
        raise argparse.ArgumentTypeError("bandwidth values must be positive")
    return values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="O-Cloud E2E smoke test with full UE iperf driver")
    parser.add_argument("--bandwidth", type=parse_bandwidths, default=[500], help="Comma-separated Mbps list")
    parser.add_argument("--period", type=int, default=10, help="iPerf duration per bandwidth in seconds")
    parser.add_argument("--gap-time", type=int, default=2, help="Gap between bandwidth steps in seconds")
    parser.add_argument("--uplink", action="store_true", help="Run UE uplink instead of downlink reverse mode")
    parser.add_argument("--ue-model", choices=["samsung", "mtk"], default="samsung")
    parser.add_argument("--iperf-bind", default="10.45.0.1", help="Local UPF/ogstun address for iperf3 server")
    parser.add_argument(
        "--settle-time",
        type=int,
        default=30,
        help="Seconds to wait after pods are ready before triggering UE attach",
    )
    parser.add_argument("--attach-timeout", type=int, default=180, help="Seconds to wait for UE 10.45.x.x attach")
    parser.add_argument(
        "--preserve-ue-state",
        action="store_true",
        help="Require an existing UE 10.45.x.x address; never toggle airplane mode",
    )
    parser.add_argument(
        "--keep-ue-online-on-failure",
        action="store_true",
        help="Do not toggle airplane mode ON if attach/iperf fails",
    )
    return parser.parse_args()


def run_cmd(cmd: list[str], timeout: int = 15) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[WARNING] Command timed out: {cmd}")
        return None


def check_k8s_pods() -> bool:
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

        print("[ERROR] Pods are not fully ready. Please check 'kubectl get pods -n ming-ns'")
        return False
    except Exception as exc:  # noqa: BLE001 - operational script boundary
        print(f"[ERROR] Failed to parse pods json: {exc}")
        return False


def stop_iperf_server(iperf_srv: subprocess.Popen[str] | None) -> tuple[str, str]:
    if iperf_srv is None:
        return "", ""
    if iperf_srv.poll() is None:
        iperf_srv.terminate()
    try:
        return iperf_srv.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        iperf_srv.kill()
        return iperf_srv.communicate(timeout=5)


def expected_iperf_runtime(args: argparse.Namespace) -> int:
    """Expected client-side runtime in seconds, excluding attach/setup."""
    tests = len(args.bandwidth)
    if tests <= 0:
        return 0
    return tests * args.period + max(0, tests - 1) * max(0, args.gap_time)


def main() -> None:
    args = parse_args()
    iperf_srv: subprocess.Popen[str] | None = None
    success = False

    try:
        # 1. Check K8s Pods status
        if not check_k8s_pods():
            sys.exit(1)

        if args.settle_time > 0:
            print(f"   > Waiting {args.settle_time}s for O-Cloud gNB/RU path to settle before UE attach...")
            time.sleep(args.settle_time)

        # 2. Make UE Driver and bring UE online
        print(f"[2/6] Initializing {args.ue_model.upper()} UE...")
        try:
            driver = make_ue_driver(args.ue_model)
        except Exception as exc:  # noqa: BLE001
            print(f"[ERROR] Failed to load {args.ue_model} UE driver: {exc}")
            sys.exit(1)

        print("   > Ensuring UE is online and has obtained 10.45.x.x IP...")
        if args.preserve_ue_state:
            ue_ip = driver.get_ip()
            if not ue_ip:
                print(
                    "[ERROR] Preserve-UE mode requires an existing 10.45.x.x address. "
                    "No airplane-mode recovery was attempted."
                )
                sys.exit(1)
            print(f"[SUCCESS] UE already online with IP: {ue_ip} (preserve-UE mode)")
        else:
            if not driver.ensure_online(timeout=args.attach_timeout):
                print(
                    "[ERROR] Failed to bring UE online. IP not obtained. "
                    "iPerf was not started because the UE did not attach."
                )
                sys.exit(1)
            ue_ip = driver.get_ip()
            print(f"[SUCCESS] UE is online with IP: {ue_ip}")

        # 3. Start local iperf3 server on UPF/ogstun.
        print(f"[3/6] Starting iperf3 server locally on ogstun ({args.iperf_bind})...")
        subprocess.run(["sudo", "pkill", "-9", "iperf3"], capture_output=True)
        time.sleep(1)

        # Persistent server: the full UE driver may run several bandwidth steps.
        iperf_srv = subprocess.Popen(
            ["iperf3", "-s", "-B", args.iperf_bind],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        time.sleep(2)

        # 4. Trigger iperf client on UE using the same driver path as Bare Metal.
        direction = "Uplink" if args.uplink else "Downlink"
        bandwidth_csv = ",".join(str(value) for value in args.bandwidth)
        print(
            f"[4/6] Starting {direction} iperf test via full UE driver "
            f"(bandwidths={bandwidth_csv} Mbps, period={args.period}s, gap={args.gap_time}s)..."
        )
        iperf_proc = driver.start_iperf_client(
            bandwidth_list=args.bandwidth,
            period=args.period,
            gap_time=args.gap_time,
            uplink=args.uplink,
        )

        os.set_blocking(iperf_proc.stdout.fileno(), False)
        watchdog_seconds = expected_iperf_runtime(args) + 120
        iperf_deadline = time.monotonic() + watchdog_seconds
        watchdog_fired = False
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
            if time.monotonic() > iperf_deadline:
                watchdog_fired = True
                print(
                    "[WARNING] UE iperf exceeded expected runtime "
                    f"({watchdog_seconds}s watchdog). Forcing UE cleanup and "
                    "continuing with server-side iperf evidence.",
                    flush=True,
                )
                driver.stop_iperf_client()
                break
            time.sleep(0.5)

        if iperf_proc.poll() is None:
            try:
                iperf_proc.terminate()
                iperf_proc.wait(timeout=5)
            except Exception:
                try:
                    iperf_proc.kill()
                except Exception:
                    pass

        if iperf_proc.returncode != 0 and not watchdog_fired:
            print(f"[ERROR] UE iperf driver exited with return code {iperf_proc.returncode}")
            sys.exit(iperf_proc.returncode)
        if watchdog_fired:
            print(
                "[WARNING] UE iperf driver did not exit cleanly, but the requested "
                "traffic window elapsed; preserving the run using server-side output."
            )

        iperf_srv_out, iperf_srv_err = stop_iperf_server(iperf_srv)
        iperf_srv = None

        print("\n--- Local iperf3 Server Output ---")
        if iperf_srv_out.strip():
            print(iperf_srv_out)
        if iperf_srv_err.strip():
            print(iperf_srv_err)
        iperf_server_text = "\n".join([iperf_srv_out or "", iperf_srv_err or ""])
        accepted_connection = "Accepted connection" in iperf_server_text
        has_interval_samples = re.search(r"\[\s*\d+\]\s+[0-9.]+-[0-9.]+\s+sec\s+.+?\s+[0-9.]+\s+Mbits/sec", iperf_server_text)
        if not accepted_connection or not has_interval_samples:
            print(
                "[ERROR] iperf server did not observe a valid UE traffic session. "
                "UE may have a 10.45.x.x address but no working user-plane path to 10.45.0.1:5201."
            )
            sys.exit(1)

        print("[SUCCESS] End-to-End UE iperf execution completed successfully!")

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
            shell=True,
        )

        print(f"   > Writing PNF logs to {pnf_log_file}...")
        subprocess.run(
            f"{KUBECTL} --kubeconfig={KUBECONFIG} logs -n {NAMESPACE} deploy/oai-pnf-pegatron > {pnf_log_file}",
            shell=True,
        )

        print(f"[FINISHED] All steps completed! Logs are saved in directory: {log_dir}")
        success = True
    finally:
        stop_iperf_server(iperf_srv)
        if "driver" in locals():
            if args.preserve_ue_state or (not success and args.keep_ue_online_on_failure):
                print("\n[6/6] Leaving UE airplane mode unchanged for failure inspection.")
            else:
                print("\n[6/6] Toggling Airplane Mode ON to save UE battery...")
                driver.airplane("on")


if __name__ == "__main__":
    main()
