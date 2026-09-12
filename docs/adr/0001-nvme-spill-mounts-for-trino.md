# ADR 0001: Local NVMe Ephemeral Storage for Trino Query Spill Partitions

- **Status**: Accepted
- **Date**: 2026-08-25
- **Deciders**: Platform SRE Team, Lakehouse Infrastructure Architect
- **Context**: Incident `INC-2026-0822-02` (Trino Coordinator OOM & Worker Spill Contention)

---

## 1. Context and Problem Statement
When analytical queries exceed available JVM worker heap memory during massive multi-way distributed joins or aggregations, Trino utilizes spill-to-disk mechanisms to prevent query failure. 

In our original deployment, worker pods utilized network-attached Ceph RBD / AWS EBS `gp3` volumes for spill paths (`/data/trino/spill`). Under high concurrency, simultaneous spill operations saturated network NIC bandwidth and SAN IOPS queues. This resulted in worker heartbeat drops, query timeouts, and cascade failure across the Trino cluster.

---

## 2. Options Considered

1. **Option A: Increase Network-Attached SAN IOPS (Ceph RBD / AWS EBS io2)**
   - *Pros*: Dynamically expandable, managed via standard Kubernetes CSI PersistentVolumes.
   - *Cons*: Prohibitively expensive across 50 production clusters; subject to network transport latency and SAN controller choke points during large bursts.
2. **Option B: Restrict Queries and Disable Spill (Fail Fast)**
   - *Pros*: Protects cluster stability by canceling long-running queries early.
   - *Cons*: Unacceptable to data science and intelligence analysts who regularly execute batch ETL queries over multi-billion row tables.
3. **Option C: Dedicated Local NVMe Ephemeral Disks (Selected)**
   - *Pros*: Millions of IOPS at microsecond latencies directly on PCI lanes, bypassing network stacks completely; zero storage cost for ephemeral lifecycle.
   - *Cons*: Nodes must possess direct-attached NVMe hardware; pods are tied to node lifetime.

---

## 3. Decision Outcome
**Selected Option C: Dedicated Local NVMe Ephemeral Disks**.
We adopted Kubernetes `local-storage` provisioner backed by RAID0 striped local PCIe NVMe drives mounted directly to `/mnt/nvme-spill` on worker nodes.

### Configuration Specification
In `trino-worker` StatefulSet:
```yaml
volumeMounts:
  - name: trino-spill-local-nvme
    mountPath: /data/trino/spill
volumes:
  - name: trino-spill-local-nvme
    hostPath:
      path: /mnt/nvme-spill
      type: Directory
```

---

## 4. Consequences
- **Positive**:
  - Spill write latency decreased from 42ms (Ceph) to 0.18ms (NVMe).
  - Network saturation on worker nodes reduced by 65% during peak ETL hours.
  - Zero Trino query failures due to spill lockups observed in 60-day post-implementation monitoring.
- **Negative / Trade-offs**:
  - Requires standardized bare-metal / GovCloud instance types equipped with local NVMe SSDs (e.g., `i3en.3xlarge` or custom DoD hardware).
  - Storage is ephemeral; if a node experiences hardware failure mid-query, the query must be retried by the coordinator.
