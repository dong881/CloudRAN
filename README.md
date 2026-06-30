# Helm Chart Catalog for OAI Network Functions & O-Cloud Deployment

本專案提供基於 O-Cloud / Kubernetes (K8s) 環境部署 OpenAirInterface (OAI) 5G 網路元件的 Helm Charts，並特別針對 **nFAPI VNF-PNF Split** 與 **O-RU (Pegatron 1G)** 進行了時序、CPU 親和性以及硬體拓撲最佳化。

---

## 1. 專案目錄結構

*   [oai-vnf](./oai-vnf)：OAI VNF (Virtual Network Function) 的 Helm Chart，運行 MAC/RLC/PDCP/RRC 與核心網對接。
*   [oai-pnf](./oai-pnf)：OAI PNF (Physical Network Function) 的 Helm Chart，運行 L1 (PHY) 並透過 DPDK/SR-IOV 與 O-RU 對接。
*   [server-configs](./server-configs)：存放針對不同物理伺服器拓撲的 Helm 覆寫設定檔 (`values.yaml` 覆寫檔案)。
*   [fix_multus_shim.sh](./fix_multus_shim.sh)：用於自動修復 CNI/Multus-shim 卡死（FailedCreatePodSandBox）的修復指令檔。

---

## 2. 伺服器部署配置與切換

因為不同的實體伺服器擁有不同的 CPU 核心數、NUMA 架構以及 PCIe 插槽位置，專案採用 `server-configs/` 資料夾來集中管理各實體伺服器的設定檔。

### A. 方案一：VNF 與 PNF 均部署在 PNF 伺服器 (Lavoisier) ─ 預設推薦
*   **硬體拓撲：** Lavoisier 為單插槽（Single Socket）、無 NUMA 節點 1（僅有 NUMA node0，共 32 核心 `0-31`）。
*   **CPU 親和性：** VNF 核心綁定設定為 `taskset -c 8-15`，避免在無 NUMA 1 的機器上因呼叫 `numactl --membind=1` 造成崩潰。
*   **部署指令：**
    ```bash
    # 預設即為 Lavoisier 參數，直接部署即可：
    helm install vnf ./oai-vnf
    helm install pnf ./oai-pnf
    ```

### B. 方案二：VNF 部署在 HPE 伺服器，PNF 部署在 PNF 伺服器 (Lavoisier)
*   **硬體拓撲：** HPE 伺服器為雙插槽（Dual Sockets），具有 NUMA node1，適合跑高運算量的 VNF。
*   **CPU 親和性：** VNF 綁定至 NUMA node1 上的 `taskset -c 8-15,40-47`，提升記憶體存取效率。
*   **部署指令：**
    ```bash
    # VNF 指定套用 HPE 伺服器的覆寫設定：
    helm install vnf ./oai-vnf -f server-configs/hpe-server/vnf-values.yaml
    
    # PNF 仍部署於 Lavoisier 伺服器以連接 RU 光纖：
    helm install pnf ./oai-pnf -f server-configs/lavoisier-server/pnf-values.yaml
    ```

---

## 3. 重要時序與運行參數說明

為了確保物理 UE 能一次順利上線，已在 ConfigMap 中對齊了 Pegatron 1G 的關鍵時序與參數：
*   **`sl_ahead = 6`**：排程時槽提前量，O-RU 運作要求為 6。
*   **`T1a_cp_dl = (285, 470)`**：下行控制面（C-Plane）視窗時間。
*   **`T1a_up = (100, 250)`**：下行用戶面（U-Plane）傳輸時間。
*   **`prach_config`**：`eAxC_offset = 4` 且 `kbar = 4`，確保 PRACH Preamble 在 FHI7.2 正常映射。

> [!NOTE]
> **關於 PNF 的 Thread Pool 設定：**
> 在 Kubernetes 受限的 Cgroup 配額下，PNF 的 `useAdditionalOptions` 參數中 **不可** 硬編碼 `--thread-pool` 的 CPU 核心 ID，否則當綁定到 Cgroup 外的核心時會觸發 `pthread_setaffinity_np` 錯誤導致 Container 崩潰。目前已還原為由 Linux 核心調配。

---

## 4. 常見問題與疑難排解

### Q1: Pod 一直處於 `ContainerCreating` 並報 `FailedCreatePodSandBox` 錯誤
如果 Kubelet 日誌出現 `plugin type="multus-shim" name="multus-cni-network" failed (add): CmdAdd (shim): timed out waiting for the condition`，代表 CNI 的 text lock 檔案卡死。
*   **解決方式：**
    直接在控制節點執行修復指令檔，會自動刪除鎖定檔並重啟 Multus CNI：
    ```bash
    ./fix_multus_shim.sh
    ```

### Q2: 重新部署的完整清理流程
在每次變更設定檔、重新編譯二進位檔或重新 build image 後，建議執行完整的清理與重灌流程：
```bash
# 1. 移除舊釋放
helm uninstall vnf pnf

# 2. 修復 CNI 狀態
./fix_multus_shim.sh

# 3. 重新安裝
helm install vnf ./oai-vnf
helm install pnf ./oai-pnf
```
