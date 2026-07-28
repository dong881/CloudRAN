# Helm Chart Catalog for OAI Network Functions & O-Cloud Deployment

本專案提供基於 O-Cloud / Kubernetes (K8s) 環境部署 OpenAirInterface (OAI) 5G 網路元件的 Helm Charts，並特別針對 **nFAPI VNF-PNF Split** 與 **O-RU (Pegatron 1G)** 進行了時序、CPU 親和性以及硬體拓撲最佳化。

---

## 1. 專案目錄結構

*   [oai-vnf](./oai-vnf)：OAI VNF (Virtual Network Function) 的 Helm Chart，運行 MAC/RLC/PDCP/RRC 與核心網對接。
*   [oai-pnf](./oai-pnf)：OAI PNF (Physical Network Function) 的 Helm Chart，運行 L1 (PHY) 並透過 DPDK/SR-IOV 與 O-RU 對接。
*   [oai-gnb](./oai-gnb)：官方 monolithic gNB Helm Chart（取自 `gitlab.eurecom.fr/oai/orchestration/charts`），用於 **RFsim** 端到端測試，不走 nFAPI VNF/PNF split，也不需要實體 O-RU。
*   [oai-nr-ue](./oai-nr-ue)：官方 OAI NR-UE（軟體 UE）Helm Chart，預設即為 RFsim 模式，與 `oai-gnb` 搭配使用。
*   [server-configs](./server-configs)：存放針對不同物理伺服器拓撲的 Helm 覆寫設定檔 (`values.yaml` 覆寫檔案)。
*   [fix_multus_shim.sh](./fix_multus_shim.sh)：用於自動修復 CNI/Multus-shim 卡死（FailedCreatePodSandBox）的修復指令檔。

---

## 1a. RFsim 端到端測試（VNF/PNF 之外的另一條路徑）

**重要：RFsim 不是 PNF 的一種模式。** `oai-pnf` / `oai-vnf` 的 ConfigMap 是寫死給實體 Pegatron O-RU（`local_rf = "no"`、DPDK/FHI7.2 fronthaul、host 上編譯的 xRAN library），沒有 RFsim 路徑。RFsim 是用一個 **monolithic gNB**（gNB 內建軟體 RF 模擬器，`local_rf = "yes"`）取代「PNF + 實體 O-RU」整條鏈路，因此做 RFsim E2E 完全不需要部署 `oai-pnf`，只需要 `oai-gnb` + `oai-nr-ue` 兩個 pod。

```bash
KUBE_CONTEXT=ming-context
NAMESPACE=ming-ns

# 1. 部署 monolithic RFsim gNB（會透過 init container 連到 BMW Open5GS AMF 192.168.8.26）
helm install gnb ./oai-gnb --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE"
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" wait --for=condition=ready pod -l app.kubernetes.io/name=oai-gnb --timeout=180s

# 2. 確認 AMF 有看到這個 gNB N2 Setup 成功後，再部署 NR-UE（服務名稱 oai-ran 已由 oai-gnb chart 固定，nrue 端預設已對齊）
helm install nrue ./oai-nr-ue --kube-context "$KUBE_CONTEXT" --namespace "$NAMESPACE"
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" wait --for=condition=ready pod -l app.kubernetes.io/name=oai-nr-ue --timeout=180s

# 3. 確認 UE 拿到 IP
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" exec -it -c nr-ue deploy/oai-nr-ue -- \
  sh -c "ifconfig oaitun_ue1 | grep -E '(^|\s)inet($|\s)'"
```

**2026-07-27 實測全通：Registration Accept → PDU Session Establishment Accept → UE 拿到 `10.45.0.x` → `ping 10.45.0.1` 5/5 成功（~8ms）。** 過程中修掉的坑，全部已固化進 chart 預設值：

*   **`oai-gnb` 必須開 multus，不能用 pod 預設網路。** `192.168.8.26` 這台 Open5GS 主機**不是** K8s node（`kubectl get nodes` 裡沒有它），對 pod overlay network（Cilium `10.0.3.0/24`）完全沒有路由。NGAP（N2）能過是因為那是 gNB 主動撥出去、走 SNAT 的連線；但 GTP-U（N3）是 UPF 主動把封包送到 gNB 宣告的 N3 IP，這條路由不存在就直接黑洞（PDU Session 建立成功、UE 拿到 IP，但雙向 ping 全部 100% packet loss）。修法是比照 `oai-vnf` 開一個 macvlan on `eno1`：`oai-gnb/values.yaml` 的 `multus.enabled: true`，IP 用 `192.168.8.200`（避開 `oai-vnf` 用的 `.199`）。
*   **`oai-nr-ue` 的 PDU Session 一定不帶 SD**，跟 `nssai_sd` 設什麼無關。這個 chart 的 `nr-ue.conf` 是舊版 `uicc0` legacy 格式（不是新版 `uicc0.pdu_sessions`），nr-uesoftmodem 的 legacy PDU-session 路徑不管 `nssai_sd` 填什麼（試過不填、十進位 `16777215`、hex 字串 `010203`），送出的 PDU Session Request 一律是 `NSSAI 1.ffffff`（SD 缺席）。所以 subscriber 和 `oai-gnb` 的 `snssaiList` 都只能用**純 `sst=1`、不帶 `sd`**，才會對上 AMF 在 `/home/hpe/all_open5gs.yaml` 的 `plmn_support.s_nssai` 第一條（純 sst=1）。
*   **Subscriber 要用 `open5gs-dbctl` 直接加，不是走 WebUI。** `192.168.8.26` 就是本機（同一台跑 Open5GS from source 的機器，MongoDB 只聽 `127.0.0.1:27017`），沒有對外開 WebUI。chart 原本預設的 `fullImsi=001010000000100` 資料庫裡沒有，已用 `open5gs-dbctl add_ue_with_apn 001010000000100 <key> <opc> oai` 補上（`sst=1`、無 `sd`、apn=`oai`，對齊上一條）。
*   `oai-nr-ue/values.yaml` 的 `-C` 已對齊 `oai-gnb/config.yaml` 的 `absoluteFrequencySSB`（`3319680000`，band n78、106 PRB、numerology 1）；`rfSimServer` 預設 `oai-ran` 跟 `oai-gnb` chart 固定的 Service 名稱一致，不用改。
*   兩邊 image tag 都固定用 `develop`（OAI 官方持續建置的最新版，沒有比這更新的 dated tag）。**gNB 和 UE 的 tag 必須同步**：混用曾經導致 RFsim socket 直接 crash（`develop` gNB 對 `2024.w32` UE），以及 `--sa` 這個 CLI flag 在新版 `nr-uesoftmodem` 直接被判定 unknown option、整個 pod crash loop。

---

## 2. 標準部署與重啟順序

VNF 必須先完成初始化並開始監聽 nFAPI P5/P7，才能啟動 PNF。若 PNF 先連線，或只重啟其中一側，可能造成 P5 SCTP 已連線但 P7 timing thread 未建立，之後會看到 `Disconnected socket` 或 PNF 將所有 request 判定為 `TOO LATE`。

```bash
KUBE_CONTEXT=ming-context
NAMESPACE=ming-ns

# 安裝或升級 VNF，並等待其 ready。
helm upgrade --install vnf ./oai-vnf \
  --kube-context "$KUBE_CONTEXT" \
  --namespace "$NAMESPACE"
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  rollout status deployment/oai-vnf --timeout=180s

# VNF ready 後才安裝或升級 PNF。
helm upgrade --install pnf ./oai-pnf \
  --kube-context "$KUBE_CONTEXT" \
  --namespace "$NAMESPACE"
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  rollout status deployment/oai-pnf-pegatron --timeout=240s
```

若兩側已部署但 nFAPI 狀態異常，使用以下順序重建連線：

```bash
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  scale deployment/oai-pnf-pegatron --replicas=0
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  rollout restart deployment/oai-vnf
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  rollout status deployment/oai-vnf --timeout=180s
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  scale deployment/oai-pnf-pegatron --replicas=1
kubectl --context "$KUBE_CONTEXT" -n "$NAMESPACE" \
  rollout status deployment/oai-pnf-pegatron --timeout=240s
```

---

## 3. 伺服器部署配置與切換

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

## 4. 重要時序與運行參數說明

為了確保物理 UE 能一次順利上線，已在 ConfigMap 中對齊了 Pegatron 1G 的關鍵時序與參數：
*   **`sl_ahead = 6`**：排程時槽提前量，O-RU 運作要求為 6。
*   **`T1a_cp_dl = (285, 470)`**：下行控制面（C-Plane）視窗時間。
*   **`T1a_up = (100, 250)`**：下行用戶面（U-Plane）傳輸時間。
*   **`prach_config`**：`eAxC_offset = 4` 且 `kbar = 4`，確保 PRACH Preamble 在 FHI7.2 正常映射。

> [!NOTE]
> **關於 PNF 的 Thread Pool 設定：**
> 在 Kubernetes 受限的 Cgroup 配額下，PNF 的 `useAdditionalOptions` 參數中 **不可** 硬編碼 `--thread-pool` 的 CPU 核心 ID，否則當綁定到 Cgroup 外的核心時會觸發 `pthread_setaffinity_np` 錯誤導致 Container 崩潰。目前已還原為由 Linux 核心調配。

---

## 5. Lavoisier PNF host build 維護契約

PNF container 會直接使用 Lavoisier host 上編譯的 OAI、DPDK 與 xRAN libraries，而不是只依賴 image 內的檔案。預設路徑集中在 `oai-pnf/values.yaml`：

| 設定 | 預設路徑 | 用途 |
|---|---|---|
| `config.oaiBuildRoot` | `/home/oai72_su/oai_mp_f_ming` | OAI workspace 根目錄 |
| `config.dpdkLibDir` | `/home/oai72_su/dpdk-stable-22.11.11/build/lib` | DPDK ABI 23 shared libraries |
| `config.dpdkDriverDir` | `/home/oai72_su/dpdk-stable-22.11.11/build/drivers` | DPDK shared PMD/plugin |
| `config.dpdkPreloadLibraries` | `librte_mempool_ring.so.23 librte_bus_pci.so.23 librte_net_iavf.so.23` | 啟動前必須 preload 的 plugins |
| `config.fhiLibDir` | `/home/oai72_su/oai_mp_f_ming/phy_k/fhi_lib/lib/build` | `libxran.so` 所在目錄 |

維護注意事項：

* `liboai_transpro.so`、DPDK 與 `libxran.so` 必須使用相容 ABI。Deployment 啟動時會驗證目錄、preload plugin 與 `ldd` 結果，缺少相依時直接 fail fast。
* xRAN K release 將 VF index 0/偶數位置映射為 U-plane、index 1/奇數位置映射為 C-plane，因此 `dpdk_devices` 與 `ru_addr` 必須維持 **U-plane 在前、C-plane 在後**。
* ConfigMap checksum 已加入 Pod template；修改 PNF ConfigMap 後 Helm upgrade 會自動觸發 rollout。
* xRAN EAL allowlist 必須由 `io_cfg->dpdk_dev[0]` 動態建立，不可保留 build tree 中的固定 PCI address。此修正位於 `/home/oai72_su/oai_mp_f_ming/phy_k` branch `oran_k_release_v1.0-fix`、commit `aa4ba67664b8`。

### 2026-07-23 PRACH duplicate incident

Pegatron O-RU 有時會對同一個 antenna/symbol 送出 2 或 4 份 metadata 與 payload 完全相同的 PRACH packet。舊程式以 `nRxPkt <= 1` 判斷 segmentation，觸發 assertion 後只停止 RU/L1 處理鏈，Pod 與 P7 thread 仍可能保持 Running。典型症狀為：

```text
PRACH segmentation is not supported
Unsupported PRACH packet layout: nRxPkt=4
ul_tti_request ... curr: 23.5 ... TOO LATE
vnf_nr_read_dispatch_message: Disconnected socket
```

OAI host source 已在 branch `nfapi-DelayManagement-BMW` 以 commit `2945a5177273` 修正：

* 檔案：`radio/fhi_72/oaioran.c`
* 僅當 2～`XRAN_MAX_RX_PKT_PER_SYM` 份 packet 的 RB start、RB size、section ID 與 payload 全部相同時去重。
* duplicate mbuf 會安全釋放；若內容不同，仍以 `Unsupported PRACH packet layout` 中止，避免把真正的 segmentation 當成 duplicate。

修改或重新 checkout OAI source 後，必須重新編譯：

```bash
cd /home/oai72_su/oai_mp_f_ming/openairinterface5g/cmake_targets/ran_build/build
sudo ninja oran_fhlib_5g
```

---

## 6. 常見問題與疑難排解

### Q1: Pod 一直處於 `ContainerCreating` 並報 `FailedCreatePodSandBox` 錯誤
如果 Kubelet 日誌出現 `plugin type="multus-shim" name="multus-cni-network" failed (add): CmdAdd (shim): timed out waiting for the condition`，代表 CNI 的 text lock 檔案卡死。
*   **解決方式：**
    直接在控制節點執行修復指令檔，會自動刪除鎖定檔並重啟 Multus CNI：
    ```bash
    ./fix_multus_shim.sh
    ```

### Q2: 重新部署的完整流程

優先使用第 2 節的 `helm upgrade --install` 與 VNF-first 順序。只有 release 確定不再需要時才 uninstall：

```bash
# 1. 先停止並移除 PNF，再移除 VNF
helm uninstall pnf --kube-context ming-context -n ming-ns
helm uninstall vnf --kube-context ming-context -n ming-ns

# 2. 僅在 CNI 確實卡住時修復
./fix_multus_shim.sh

# 3. 依 VNF-first 順序重裝
helm install vnf ./oai-vnf --kube-context ming-context -n ming-ns
kubectl --context ming-context -n ming-ns rollout status deployment/oai-vnf --timeout=180s
helm install pnf ./oai-pnf --kube-context ming-context -n ming-ns
```

### Q3: Pod 卡在 `Terminating` 狀態無法關閉
如果執行 `helm uninstall` 後，Pod 長時間處於 `Terminating` 狀態，代表 DPDK 記憶體/PCI 資源未正常釋放或 Multus 網路介面移除發生死鎖。
*   **解決方式：**
    使用 `--force --grace-period=0` 來強制刪除 Pod：
    ```bash
    kubectl delete pod <pod-name> -n ming-ns --grace-period=0 --force
    ```

### Q4: 如何判斷 VNF/PNF 是否真的健康

Pod `Running` 不代表 RU/L1 thread 正常。至少確認以下項目：

```bash
# Pod 與 restart count
kubectl --context ming-context -n ming-ns get pods -o wide

# VNF 必須監聽 P7 UDP 50011，P5 SCTP 必須 ESTABLISHED
kubectl --context ming-context -n ming-ns exec deployment/oai-vnf -- \
  sh -c 'ss -lnup | grep 50011; ss -H -n -A sctp | grep 50005'

# PNF 必須監聽 P7 UDP 50010
kubectl --context ming-context -n ming-ns exec deployment/oai-pnf-pegatron -- \
  sh -c 'ss -lnup | grep 50010; ss -H -n -A sctp | grep 50005'

# 不應持續出現下列錯誤
kubectl --context ming-context -n ming-ns logs deployment/oai-pnf-pegatron | \
  grep -E 'Assertion|Unsupported PRACH|out of buffer window|TOO LATE|Exiting execution'
```

啟動交界偶發單筆低於 1 ms 的 `TOO LATE` 可以觀察；若持續增加，或 `curr` 固定不動，表示 RU/L1 timing chain 已停止，必須先檢查 PRACH assertion，而不是只放大 timing window。
