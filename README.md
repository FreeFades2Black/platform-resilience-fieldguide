# Field SRE Operations, Failure Scenarios & Runbook Vault

[![Operational Status](https://img.shields.io/badge/Fleet_Status-50%20Clusters%20Healthy-00aa55?style=flat-square&logo=kubernetes)](https://github.com/FreeFades2Black/platform-resilience-fieldguide)
[![MTTR Target](https://img.shields.io/badge/Target_MTTR-%3C30m-blue?style=flat-square)](https://github.com/FreeFades2Black/platform-resilience-fieldguide)
[![RCA Standards](https://img.shields.io/badge/Post_Mortem-Blameless_RCA-orange?style=flat-square)](https://github.com/FreeFades2Black/platform-resilience-fieldguide/tree/main/docs/incidents)
[![DoD Compliance](https://img.shields.io/badge/Security-Platform_One_STIG-red?style=flat-square)](https://github.com/FreeFades2Black/platform-resilience-fieldguide)

An enterprise-grade operational resilience repository, incident post-mortem archive, and executable runbook vault engineered for managing ~50 production Kubernetes clusters across hybrid GovCloud and air-gapped federal enclaves.

---

## 1. Operational Scope & Fleet Topology

The platform coordinates distributed lakehouse engines (Trino 435, Apache Iceberg, Strimzi Kafka, Spark on K8s) deployed across three operational tiers:

```
+-----------------------------------------------------------------------------+
|                           FLEET TOPOLOGY (50 CLUSTERS)                      |
+-----------------------------------------------------------------------------+
|  Ring 0 (Canary)         |  site01 - site02   | 2 Clusters  | Auto-Verify   |
|  Ring 1 (Core GovCloud)  |  site03 - site25   | 23 Clusters | Multi-AZ Gov  |
|  Ring 2 (Classified)     |  site26 - site50   | 25 Clusters | Air-Gapped    |
+-----------------------------------------------------------------------------+
```

When operating at this scale, distributed systems do not fail gracefully in isolation. Network overlays desynchronize, CSI drivers throttle during broker failovers, and heavy analytical joins generate extreme storage and memory pressure.

This repository codifies our field-tested operational knowledge into **blameless post-mortems with genuine diagnostic logs**, **reproducible runbooks**, **Prometheus alerting rules**, and **safe automated remediation scripts**.

---

## 2. Master Incident Post-Mortem Index (RCAs)

Every incident documented in this repository reflects real failure dynamics encountered in field operations, complete with raw terminal outputs, kernel `dmesg` traces, and causal analysis:

| Incident ID | Target Failure Scenario | Impacted Substrate | Primary Root Cause | Key Remediation |
|---|---|---|---|---|
| [`INC-2026-0814-01`](docs/incidents/001-cross-site-pvc-deadlock.md) | **Cross-Site PVC Deadlock** | Strimzi Kafka / Ceph CSI | Ceph MON API throttling + `attachdetach-controller` backoff loop | Tuned CSI workers; enabled `WaitForFirstConsumer` |
| [`INC-2026-0822-02`](docs/incidents/002-trino-coordinator-oom-spill-disk.md) | **Trino Coordinator OOM** | Trino 435 / NVMe Spill | 180k+ tiny spill file pointers saturating JVM heap tracking | Set 64MB min spill chunks; adopted local NVMe mounts ([ADR 0001](docs/adr/0001-nvme-spill-mounts-for-trino.md)) |
| [`INC-2026-0901-03`](docs/incidents/003-cni-mtu-asymmetry-istio-upgrade.md) | **CNI MTU Asymmetry** | Cilium eBPF / Istio Mesh | Mesh Geneve encapsulation exceeding 1420-byte WireGuard transit | Standardized pod MTU to 1350; enabled eBPF host-routing ([ADR 0002](docs/adr/0002-ebpf-host-routing-over-iptables-for-mesh.md)) |
| [`INC-2026-0908-04`](docs/incidents/004-stale-k8s-leases-split-brain.md) | **Stale Leases & Split-Brain** | Kube-Controller / Spark | Control plane network partition causing deadlocked finalizers | Tuned lease renew timeouts; created [`lease_pruner.py`](scripts/lease_pruner.py) |

---

## 3. Executable Triage Runbooks

Runbooks provide clear, deterministic guidance with cut-and-paste commands, PromQL queries, and fallback paths:

- **[RB-LAKEHOUSE-001: Triaging Lakehouse Ingest Lag](runbooks/01-triage-lakehouse-ingest-lag.md)**
  - PromQL queries for topic consumer group partition lag.
  - Broker under-replicated partition inspection and partition rebalance commands.
  - Safe consumer pod autoscaling.

- **[RB-COMPUTE-002: Recovering Stuck Spark Driver Pods](runbooks/02-recovering-stuck-spark-driver-pods.md)**
  - Triage protocol for pods indefinitely stuck in `Terminating`.
  - Spark History Server completion verification.
  - Automated and manual finalizer stripping procedures.

- **[RB-AIRGAP-003: Disconnected Registry Mirroring](runbooks/03-disconnected-registry-mirroring.md)**
  - Procedures for air-gapped / sovereign enclaves (Ring 2).
  - Skopeo archive exports, Platform One Cosign cryptographic verification, and Harbor ingestion.

---

## 4. Architecture Decision Records (ADRs)

- **[ADR 0001: Local NVMe Ephemeral Storage for Trino Query Spill Partitions](docs/adr/0001-nvme-spill-mounts-for-trino.md)**
  - Details the evaluation of Ceph RBD, AWS EBS `gp3`, and direct-attached NVMe SSDs.
  - Justifies accepting local ephemeral node affinity in exchange for a 230x reduction in write latency.

- **[ADR 0002: Cilium eBPF Host Routing Over Kube-Proxy Iptables](docs/adr/0002-ebpf-host-routing-over-iptables-for-mesh.md)**
  - Documents how eBPF direct host routing eliminated connection tracking (`conntrack`) table exhaustion under heavy Spark shuffle exchanges.

---

## 5. Monitoring & Golden Signals as Code

### Prometheus Alerts (`PrometheusRule`)
Location: [`monitoring/prometheus/lakehouse_sre_rules.yaml`](monitoring/prometheus/lakehouse_sre_rules.yaml)
- `LakehouseKafkaConsumerLagCritical` (>50,000 msgs for 5m)
- `TrinoCoordinatorMemorySaturation` (>88% memory working set for 3m)
- `TrinoQuerySpillPressureHigh` (>500MB/s spill write rate)
- `CSIVolumeAttachTimeoutExceeded` (>0.05 attach failures/s)
- `CNIPacketDropRatioHigh` (>2% eBPF packet drops)
- `KubeLeaseRenewalStalled` (renew delta > 30s)

### Grafana Cockpit
Location: [`monitoring/grafana/lakehouse_sre_dashboard.json`](monitoring/grafana/lakehouse_sre_dashboard.json)
Visualizes end-to-end telemetry across storage attachment latency, Kafka consumer lag, query spill throughput, and network packet drop ratios.

---

## 6. SRE Automation Tooling

The [`scripts/`](scripts/) directory contains audited operational CLI utilities:
- **`lease_pruner.py`**: Discovers stalled leases and safely prunes deadlocked finalizers on completed pods. Defaults to `--check-only` (dry-run).
- **`validate_cni_mtu.py`**: Probes inter-node transit path MTU and detects fragmentation drops before application traffic suffers.

---

## 7. Verification & Testing

Execute the full verification harness:
```bash
make test
```
The test suite validates:
1. Post-mortem Markdown structure across all required RCA sections.
2. Runbook existence and syntax consistency.
3. Prometheus alerting rules YAML schema and alert metadata annotations.
4. Grafana dashboard JSON schema integrity.
5. Python remediation script functionality (dry-run and active modes).
