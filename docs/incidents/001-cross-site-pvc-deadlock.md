# Incident RCA: Cross-Site PVC Deadlock Under Heavy Ingestion

- **Incident ID**: INC-2026-0814-01
- **Severity**: SEV-1 (Critical Data Ingestion Interruption)
- **Impacted Systems**: Strimzi Kafka Brokers (Site-07, Site-12), Ceph CSI Volume Provisioner
- **Detection Time**: 2026-08-14 03:14:22 UTC
- **Mitigation Time**: 2026-08-14 04:02:15 UTC
- **MTTR**: 47m 53s

---

## Executive Summary
During a scheduled failover drill in Region East (Site-07), three Kafka broker StatefulSet pods were rescheduled to secondary worker nodes. Simultaneously, a burst of telemetry ingestion generated high I/O throughput across Kafka storage volumes. The Ceph CSI volume plugin entered a lock contention loop where volume detach operations timed out after 120 seconds while the destination nodes repeatedly failed `AttachVolume` calls with `VolumeInUse`. This produced a cascading PVC deadlock that degraded Kafka consumer lag past critical thresholds.

---

## Timeline of Events

| Timestamp (UTC) | Event Description |
|---|---|
| 03:14:22 | Automated node drain initiated on worker `node-s07-w03` hosting Kafka broker pod `kafka-broker-02`. |
| 03:15:10 | `kafka-broker-02` terminated gracefully; CSI volume detach signal transmitted to Ceph gateway. |
| 03:16:30 | Heavy burst ingestion spikes disk write queues on neighbor nodes (`node-s07-w04`, `node-s07-w05`). |
| 03:17:10 | Ceph CSI driver API gateway experiences request queue saturation; detach times out. |
| 03:19:00 | Kubernetes `attachdetach-controller` enters exponential backoff (retrying every 6m). |
| 03:22:45 | Prometheus alert `KafkaConsumerLagCritical` fires for topic `lakehouse-telemetry-raw`. |
| 03:25:12 | On-call SRE paged; initiates runbook triage for storage volume mount failures. |
| 03:41:00 | SRE executes CSI lock release sequence and removes dangling VolumeAttachment lock. |
| 03:52:30 | `kafka-broker-02` successfully attaches volume on `node-s07-w06` and initiates ISR partition sync. |
| 04:02:15 | Kafka cluster returns to green ISR status; consumer lag drops back to baseline (<15ms). |

---

## Terminal & Diagnostic Artifacts

### 1. Pod Status and Attachment Failure
```console
$ kubectl describe pod kafka-broker-02 -n lakehouse-infra
Events:
  Type     Reason              Age                 From                     Message
  ----     ------              ----                ----                     -------
  Normal   Scheduled           15m                 default-scheduler        Successfully assigned lakehouse-infra/kafka-broker-02 to node-s07-w06
  Warning  FailedAttachVolume  14m (x12 over 15m)  attachdetach-controller  Multi-Attach error for volume "pvc-89b1c72e-c1e5-429f-85a7-937eef554012" Volume is already exclusively attached to one node and can't be attached to another
  Warning  FailedMount         3m (x4 over 9m)     kubelet                  Unable to attach or mount volumes: timed out waiting for the condition
```

### 2. Node Kernel Dmesg Traces
```console
# dmesg -T | grep -E "rbd|ceph|blk"
[Fri Aug 14 03:16:55 2026] libceph: osd32 10.240.12.89:6804 connection reset
[Fri Aug 14 03:17:02 2026] rbd: rbd0: block request 0xffff9a88c0 expired after 120000ms
[Fri Aug 14 03:17:03 2026] rbd: rbd0: exclusive-lock release timed out, retaining lock
[Fri Aug 14 03:18:22 2026] rbd: rbd0: aborting I/O requests due to lock transition deadlock
```

### 3. CSI Controller Logs
```console
$ kubectl logs -n ceph-csi-system ceph-csi-rbdplugin-provisioner-7f89c687d-8bkl2 -c csi-attacher --tail=50
I0814 03:16:35.129381 csi_handler.go:210] Detaching volume pvc-89b1c72e-c1e5-429f-85a7-937eef554012 from node node-s07-w03
E0814 03:18:35.130291 csi_handler.go:215] Detach failed for volume pvc-89b1c72e-c1e5-429f-85a7-937eef554012: context deadline exceeded (Client.Timeout exceeded while awaiting headers)
E0814 03:18:35.130452 connection.go:183] GRPC error: rpc error: code = DeadlineExceeded desc = Ceph API gateway timeout during lock unmap
```

---

## Root Cause Analysis
1. **CSI Driver Request Starvation**: The Ceph CSI controller deployment was configured with a single replica without rate-limiting concurrency controls against the Ceph MON/OSD API. During concurrent failover and heavy volume writes, the HTTP connection pool to the Ceph manager was exhausted.
2. **Exponential Backoff in attachdetach-controller**: When the detach API call timed out, the Kubernetes `attachdetach-controller` registered a failure and backed off exponentially up to 6 minutes before attempting the next attach/detach cycle.
3. **StorageClass Binding Semantics**: The StorageClass had `volumeBindingMode: Immediate` configured instead of `WaitForFirstConsumer`, preventing optimal scheduler node selection based on local SAN fabric topology.

---

## Corrective & Preventative Actions
1. **CSI Concurrency & Timeout Tuning**:
   - Increased CSI attacher gRPC timeout from 120s to 180s.
   - Configured CSI provisioner with `worker-threads: 16` and connection pool keepalives.
2. **StorageClass Policy Enforcement**:
   - Switched all lakehouse persistent volumes to `volumeBindingMode: WaitForFirstConsumer`.
3. **Automated Deadlock Recovery**:
   - Developed `scripts/lease_pruner.py` to identify orphaned `VolumeAttachment` resources holding stale locks during node evictions.
