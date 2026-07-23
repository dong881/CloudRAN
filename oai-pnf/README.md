# Helm Chart for OAI Next Generation Node B (OAI-gNB) Fronthaul 7.2

**These charts are not finalized so the documentation is not complete. Please do not ask for any support on mailing list**

These charts are only tested on Openshift.

## Introduction

To know more about the feature set of OpenAirInterface you can check it [here](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/FEATURE_SET.md#openairinterface-5g-nr-feature-set). 

The [codebase](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tree/develop) for gNB, CU, DU, CU-CP/CU-UP, NR-UE is the same. 

It is strongly recommended that you read about [OAI 7.2 implementation](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/ORAN_FHI7.2_Tutorial.md?ref_type=heads)

## Prerequisite

1. Configure the baremetal gNB/DU server as mentioned in this [tutorial](https://gitlab.eurecom.fr/oai/openairinterface5g/-/blob/develop/doc/ORAN_FHI7.2_Tutorial.md?ref_type=heads#configure-your-server) 
2. Before using the helm-charts you have to create two dedicated `SriovNetworkNodePolicy` for C and U plane. 

Using below Kubernetes manifest

```yaml
apiVersion: sriovnetwork.openshift.io/v1
kind: SriovNetworkNodePolicy
metadata:      
  name: RESOURCE_NAME_U_PLANE
  namespace: openshift-sriov-network-operator
spec:
  resourceName: RESOURCE_NAME_U_PLANE
  nodeSelector:
    feature.node.kubernetes.io/network-sriov.capable: "true"
  priority: 11
  mtu: 9216
  deviceType: vfio-pci
  isRdma: false
  numVfs: 4
  linkType: eth
  nicSelector:
    pfNames:
      - 'PHYSICAL_INTERFACE#0-1'     # Same device specified by rootDevices
    rootDevices:
      - 'PCI_ADDRESS_OF_THE_PHYSICAL_INTERFACE' # PCI bus address
---
apiVersion: sriovnetwork.openshift.io/v1
kind: SriovNetworkNodePolicy
metadata:      
  name: RESOURCE_NAME_C_PLANE
  namespace: openshift-sriov-network-operator
spec:
  resourceName: RESOURCE_NAME_C_PLANE
  nodeSelector:
    feature.node.kubernetes.io/network-sriov.capable: "true"
  priority: 12
  mtu: 9216
  deviceType: vfio-pci
  isRdma: false
  numVfs: 4
  linkType: eth
  nicSelector:
    pfNames:
      - 'PHYSICAL_INTERFACE#2-3'     # Same device specified by rootDevices
    rootDevices:
      - 'PCI_ADDRESS_OF_THE_PHYSICAL_INTERFACE' # PCI bus address
```

## How to configure the charts

The helm chart of OAI-GNB creates multiples Kubernetes resources,

1. Service
2. Role Base Access Control (RBAC) (role and role bindings)
3. Deployment
4. Configmap
5. Service account
6. Network-attachment-definition (Optional only when multus is used)

The directory structure

```
.
├── Chart.yaml
├── templates
│   ├── configmap.yaml (All the configuration is there)
│   ├── deployment.yaml
│   ├── _helpers.tpl
│   ├── multus.yaml
│   ├── NOTES.txt
│   ├── rbac.yaml
│   ├── serviceaccount.yaml
│   └── service.yaml
└── values.yaml
```

## Container Images 

For openshift you have to [build images](https://gitlab.eurecom.fr/oai/openairinterface5g/-/tree/fhi-container/openshift?ref_type=heads). 

For Ubuntu you can pull the image from docker-hub --> https://hub.docker.com/r/arorasagar/oai-gnb-fhi72

## Parameters

[Values.yaml](./values.yaml) contains all the configurable parameters. Below table defines the configurable parameters. You need a dedicated interface for Fronthaul and N2. 


|Parameter                       |Allowed Values                 |Remark                                          |
|--------------------------------|-------------------------------|------------------------------------------------|
|kubernetesType                  |Vanilla/Openshift              |Vanilla Kubernetes or Openshift                 |
|nfimage.repository              |Image Name                     |                                                |
|nfimage.version                 |Image tag                      |                                                |
|nfimage.pullPolicy              |IfNotPresent or Never or Always|                                                |
|imagePullSecrets.name           |String                         |Good to use for docker hub                      |
|serviceAccount.create           |true/false                     |                                                |
|serviceAccount.annotations      |String                         |                                                |
|serviceAccount.name             |String                         |                                                |
|podSecurityContext.runAsUser    |Integer (0,65534)              |                                                |
|podSecurityContext.runAsGroup   |Integer (0,65534)              |                                                |
|multus.defaultGateway           |Ip-Address                     |default route in the pod                        |
|multus.n2Interface.create       |true/false                     |                                                |
|multus.n2Interface.IPadd        |Ip-Address                     |                                                |
|multus.n2Interface.Netmask      |Netmask                        |                                                |
|multus.n2Interface.Gateway      |Ip-Address                     |                                                |
|multus.n2Interface.hostInterface|host interface                 |Host interface of the machine where pod will run|
|multus.n2Interface.routes       |Json                           |Routes you want to add in the pod               |
|multus.n3Interface.create       |true/false                     |(Optional not necessary)                                                |
|multus.n3Interface.IPadd        |Ip-Address)                    |                                                |
|multus.n3Interface.Netmask      |Netmask                        |                                                |
|multus.n3Interface.Gateway      |Ip-Address                     |                                                |
|multus.n3Interface.hostInterface|host interface                 |Host interface of the machine where pod will run|
|multus.n3Interface.routes       |Json                           |Routes you want to add in the pod               |
|config.oaiBuildRoot             |Absolute host path             |OAI workspace root mounted from the PNF node    |
|config.dpdkLibDir               |Absolute host path             |DPDK shared library directory; ABI must match OAI|
|config.dpdkDriverDir            |Absolute host path             |DPDK shared PMD/plugin directory                |
|config.dpdkPreloadLibraries     |Space-separated library names  |Shared DPDK plugins preloaded before OAI starts |
|config.fhiLibDir                |Absolute host path             |Directory containing the compatible `libxran.so`|


These fields depends on the O-RU and Kubernetes distribution. The `ruInterface.sriovNetworkNamespace` will change with Kubernetes distribution.

```
  ruInterface:            #Only needed if using a ethernet based RU/USRP
    create: true
    mtu: 9216
    vlan: 564
    cPlaneMacAdd: 00:11:22:33:44:66
    uPlaneMacAdd: 00:11:22:33:44:66 
    sriovNetworkNamespace: openshift-sriov-network-operator
    sriovResourceNameCplane: ruvfioc
    sriovResourceNameUplane: ruvfiou
```

The config parameters mentioned in `config` block of `values.yaml` are limited on purpose to maintain simplicity. They do not allow changing a lot of parameters of oai-gnb. If you want to use your own configuration file for oai-gnb. It is recommended to copy it in `templates/configmap.yaml`. The command line for gnb is provided in `config.useAdditionalOptions`. 

There are certain fields in `templates/configmap.yaml` with `@CONFIG_VALUE@` these fields are very important to configure the CPU threads, mac addresses and PLMN. Apart from these fields you can change any parameter. 

The charts are configured to be used with primary CNI of Kubernetes. When you will mount the configuration file you have to define static ip-addresses for N2, N3 and RU. Most of the primary CNIs do not allow static ip-address allocation. To overcome this we are using multus-cni with static ip-address allocation. 

## Lavoisier host-library requirements

This chart runs the host-built `nr-softmodem` and loads host OAI, DPDK and xRAN libraries. The container startup validates every configured directory, explicitly preloads the shared DPDK ring/PCI/iavf plugins, and checks `liboai_transpro.so` with `ldd`. A missing or ABI-incompatible dependency therefore fails at startup instead of producing a partially working PNF.

Keep the following invariants when changing the build or server:

1. `liboai_transpro.so`, DPDK shared libraries and `libxran.so` must use compatible ABIs.
2. xRAN K release expects the U-plane VF/MAC first and the C-plane VF/MAC second. Do not reverse `dpdk_devices` or `ru_addr`.
3. The xRAN EAL allowlist must be generated from `io_cfg->dpdk_dev[0]`; a hard-coded PCI address can make EAL initialize without the assigned SR-IOV VF. This fix is commit `aa4ba67664b8` on branch `oran_k_release_v1.0-fix` in `/home/oai72_su/oai_mp_f_ming/phy_k`.
4. A ConfigMap checksum is part of the Deployment Pod template, so use `helm upgrade` after configuration changes and wait for the rollout.

The Pegatron O-RU can emit repeated, byte-identical PRACH packets. The required OAI-side fix is commit `2945a5177273` on branch `nfapi-DelayManagement-BMW`, in `radio/fhi_72/oaioran.c`. It deduplicates only packets whose RB metadata, section ID and payload are all identical; non-identical multi-packet PRACH remains unsupported and fails explicitly.

Rebuild the OAI fronthaul library after changing or restoring that source:

```bash
cd /home/oai72_su/oai_mp_f_ming/openairinterface5g/cmake_targets/ran_build/build
sudo ninja oran_fhlib_5g
```

For the complete incident symptoms, recovery order and health checks, see the repository-level [README](../README.md).

## Advanced Debugging Parameters

Only needed if you are doing advanced debugging

|Parameter                        |Allowed Values                 |Remark                                        |
|---------------------------------|-------------------------------|----------------------------------------------|
|start.gnb                        |true/false                     |If true gnb container will go in sleep mode   |
|start.tcpdump                    |true/false                     |If true tcpdump container will go in sleepmode|
|includeTcpDumpContainer          |true/false                     |If false no tcpdump container will be there   |
|tcpdumpimage.repository          |Image Name                     |                                              |
|tcpdumpimage.version             |Image tag                      |                                              |
|tcpdumpimage.pullPolicy          |IfNotPresent or Never or Always|                                              |
|persistent.sharedvolume          |true/false                     |Save the pcaps in a shared volume with NRF    |
|readinessProbe                   |true/false                     |default true                                  |
|livenessProbe                    |true/false                     |default false                                 |
|terminationGracePeriodSeconds    |5                              |In seconds (default 5)                        |
|nodeSelector                     |Node label                     |                                              |
|nodeName                         |Node Name                      |                                              |


Depending on your distribution of Kubernetes cluster `resources.limits.nf.sriovXplaneClaim.name` will change. 

```
resources:
  define: true
  limits:
    nf:
      cpu: 8
      memory: 8Gi
      # size of the hugepages is 1 Gi
      hugepages: 10Gi
      sriovCplaneClaim:
        name: openshift.io/ruvfioc
        quantity: 1
      sriovUplaneClaim:
        name: openshift.io/ruvfiou
        quantity: 1
    #If tcpdump container is disabled this value will not be used
    tcpdump:
      cpu: 100m
      memory: 128Mi
  requests:
    nf:
      cpu: 8
      memory: 8Gi
      # size of the hugepages is 1 Gi
      hugepages: 10Gi
      sriovCplaneClaim:
        name: openshift.io/ruvfioc
        quantity: 1
      sriovUplaneClaim:
        name: openshift.io/ruvfiou
        quantity: 1
    #If tcpdump container is disabled this value will not be used
    tcpdump:
      cpu: 100m
      memory: 128Mi
```



## How to use

1. Check the networking, host-library parameters and configuration in `templates/configmap.yaml`.
2. Install and wait for VNF first. Start PNF only after VNF is ready, otherwise P5 may reconnect without a working P7 timing path.

```bash
helm upgrade --install vnf ../oai-vnf --kube-context ming-context -n ming-ns
kubectl --context ming-context -n ming-ns rollout status deployment/oai-vnf --timeout=180s
helm upgrade --install pnf . --kube-context ming-context -n ming-ns
kubectl --context ming-context -n ming-ns rollout status deployment/oai-pnf-pegatron --timeout=240s
```


## Note

1. If you are using multus then make sure it is properly configured and if you don't have a gateway for your multus interface then avoid using gateway and defaultGateway parameter. Either comment them or leave them empty. Wrong gateway configuration can create issues with pod networking and pod will not be able to resolve service names.
