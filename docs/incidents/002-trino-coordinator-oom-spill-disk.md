# Incident RCA: Trino Coordinator OOM Under Spill-to-Disk Contention

- **Incident ID**: INC-2026-0822-02
- **Severity**: SEV-1 (Distributed Query Engine Outage)
- **Impacted Systems**: Trino Distributed Query Engine 435 (GovCloud Cluster `site-19`)
- **Detection Time**: 2026-08-22 14:18:04 UTC
- **Mitigation Time**: 2026-08-22 14:49:10 UTC
- **MTTR**: 31m 06s

---

## Executive Summary
A massive analytical query executing a multi-way join across 2.4 billion Iceberg table rows triggered spill-to-disk on all 24 Trino worker nodes. Due to misconfigured NVMe disk write buffering and synchronous spill tracking on the coordinator, the coordinator JVM spent >92% of CPU time in G1 garbage collection pauses tracking worker spill file pointers. The Linux kernel OOM killer terminated the coordinator pod (`trino-coordinator-0`), aborting 84 concurrently active queries and leaving downstream lakehouse pipelines stalled.

---

## Timeline of Events

| Timestamp (UTC) | Event Description |
|---|---|
| 14:18:04 | Data science batch job triggers query `20260822_141804_00012_x78p9` joining raw telemetry with geospatial entity dimensions. |
| 14:20:12 | Trino query memory exceeds query limit (250GB); workers begin spilling partition blocks to `/data/trino/spill`. |
| 14:22:45 | Worker nodes generate 180,000+ small spill files (avg size 1.2MB) due to low spill chunk buffer sizes. |
| 14:24:30 | Worker status heartbeats convey high volumes of spill metadata to the coordinator. |
| 14:26:15 | Coordinator JVM heap usage hits 98.4%; G1GC enters Full GC evacuation freeze lasting 14.8 seconds. |
| 14:27:02 | Kubelet liveness probe to `http://trino-coordinator:8080/v1/info` fails (timeout > 5s). |
| 14:27:40 | Linux kernel OOM-killer invokes `oom_reap_task` on PID 184920 (`java`). |
| 14:28:10 | Prometheus alert `TrinoCoordinatorMemorySaturation` fires. |
| 14:32:00 | SRE deploys emergency configuration patch adjusting JVM reserve heap and query spill file chunk minimums. |
| 14:49:10 | Trino coordinator stabilizes; query admission queue recovers with verified spill-to-disk bounds. |

---

## Terminal & Diagnostic Artifacts

### 1. Coordinator JVM GC Logs
```console
[2026-08-22T14:26:15.102+0000] GC(142) Pause Full (G1 Evacuation Pause) (G1 Compaction Pause)
[2026-08-22T14:26:15.102+0000] GC(142) Pre-evacuate collection set: 12.4ms
[2026-08-22T14:26:15.114+0000] GC(142) Evacuate Collection Set: 14120.3ms
[2026-08-22T14:26:29.234+0000] GC(142) Humongous regions before: 4120, after: 3980
[2026-08-22T14:26:29.890+0000] GC(142) Heap: 61440.0M(61440.0M)->60912.4M(61440.0M)
[2026-08-22T14:26:29.891+0000] GC(142) Total pause time: 14789.2ms
```

### 2. Linux OOM-Killer Kernel Dmesg
```console
$ dmesg -T | grep -E "Out of memory|Killed process"
[Sat Aug 22 14:27:40 2026] Out of memory: Kill process 184920 (java) score 982 or sacrifice child
[Sat Aug 22 14:27:40 2026] Killed process 184920 (java) total-vm:68412896kB, anon-rss:62914560kB, file-rss:0kB, shmem-rss:0kB
[Sat Aug 22 14:27:41 2026] oom_reaper: reaped process 184920 (java), now anon-rss:0kB
```

### 3. Jstack Thread Contention Trace on Coordinator
```console
$ jstack -l 184920 | grep -A 10 "io.trino.spiller"
"query-execution-481" #192 daemon prio=5 os_prio=0 cpu=14812.11ms elapsed=420.12s tid=0x00007f98b4109000 nid=0x2d2c8 waiting on condition [0x00007f987110e000]
   java.lang.Thread.State: WAITING (parking)
\tat jdk.internal.misc.Unsafe.park(java.base@17.0.9/Native Method)
\t- parking to wait for  <0x00000007018fa090> (a java.util.concurrent.CompletableFuture$Signaller)
\tat java.util.concurrent.locks.LockSupport.park(java.base@17.0.9/LockSupport.java:211)
\tat io.trino.spiller.FileSingleStreamSpiller.flushSpillBuffer(FileSingleStreamSpiller.java:188)
\tat io.trino.operator.HashBuilderOperator.finish(HashBuilderOperator.java:312)

$ cat /sys/fs/cgroup/memory/memory.stat | grep -E "hierarchical_memory_limit|rss"
rss 64424509440
rss_huge 2097152000
hierarchical_memory_limit 68719476736 # 64Gi limit hit: 98.8% consumption
```

### 4. Kubelet Pod Termination Record
```console
$ kubectl get pod trino-coordinator-0 -n lakehouse-infra -o yaml | grep -A 8 lastState:
    lastState:
      terminated:
        containerID: containerd://904bf782c9e10293847afb
        exitCode: 137
        finishedAt: "2026-08-22T14:27:42Z"
        reason: OOMKilled
        startedAt: "2026-08-10T08:00:00Z"
```

---

## Root Cause Analysis
1. **Unthrottled Spill Chunk Fragmentation**: Workers were configured with default spill segment sizes of 4MB. When streaming hash joins spilled, each worker produced thousands of tiny spill files, saturating the coordinator's in-memory query task tracking graph.
2. **Missing Off-Heap JVM Overhead Margin**: The pod's Kubernetes memory limit was set to 64Gi while the JVM `-Xmx` was set to 60Gi. Off-heap memory (native buffers, thread stacks, metaspace, GC card tables) exceeded the remaining 4Gi buffer under high concurrency.
3. **Single Spill Mount Contention**: Spill storage utilized a shared root ephemeral volume rather than dedicated NVMe volumes with asynchronous write batching.

---

## Corrective & Preventative Actions
1. **Configured Spill Chunk Limits & Compression**:
   - Set `experimental.spill-compression-codec=LZ4`.
   - Set `experimental.spiller-spill-path-min-free-space=20GB`.
   - Increased minimum spill chunk size to 64MB to reduce file pointer count by 16x.
2. **JVM Heap Sizing Ratio Revision**:
   - Adjusted coordinator JVM `-Xmx` to 48Gi within a 64Gi cgroup limit (75% ratio), guaranteeing 16Gi for off-heap allocations and metaspace.
3. **Dedicated NVMe Storage**:
   - Adopted ADR `0001-nvme-spill-mounts-for-trino.md` mounting host local NVMe drives (`/mnt/nvme-spill`) with `ReadWriteOnceLocal` storage class.
