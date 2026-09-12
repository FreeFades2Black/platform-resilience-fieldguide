# Incident RCA: CNI MTU Asymmetry & Spark Shuffle Dropping During Istio Mesh Upgrade

- **Incident ID**: INC-2026-0901-03
- **Severity**: SEV-1 (Inter-Node Data Plane Packet Loss)
- **Impacted Systems**: Cilium eBPF CNI, Istio Service Mesh 1.22, Apache Spark on K8s
- **Detection Time**: 2026-09-01 19:22:18 UTC
- **Mitigation Time**: 2026-09-01 20:15:40 UTC
- **MTTR**: 53m 22s

---

## Executive Summary
Following a minor version upgrade of the Istio service mesh in air-gapped staging cluster `site-34`, large distributed Spark shuffle operations began failing intermittently with `FetchFailedException: Connection reset by peer`. Small control-plane queries and synthetic probes passed with 100% success. Investigation revealed that the new Istio CNI sidecar tunnel encapsulation added a 50-byte Geneve header overhead that clashed with the host MTU. Inter-node packets larger than 1450 bytes had their `DF` (Don't Fragment) bit set, causing silent blackholing by intermediate edge switches.

---

## Timeline of Events

| Timestamp (UTC) | Event Description |
|---|---|
| 19:22:18 | GitOps rollout completes Istio 1.22 data plane daemonset upgrade on `site-34`. |
| 19:25:00 | Scheduled lakehouse ETL batch job launches Spark driver with 32 executor pods. |
| 19:30:15 | Spark stages 0 through 3 (in-memory map) succeed. Stage 4 (shuffle exchange) commences. |
| 19:31:40 | Executors fail fetching shuffle blocks across different physical nodes; errors report socket resets. |
| 19:34:02 | Spark driver aborts with `SparkException: Job aborted due to stage failure`. |
| 19:38:10 | Network SRE initiates packet inspection across inter-node interfaces using `tcpdump`. |
| 19:44:20 | `tcpdump` confirms ICMP `Fragmentation Needed` packets dropped by firewall drop policy. |
| 19:58:00 | SRE validates MTU mismatch: Host MTU=1500, WireGuard transit=1420, Pod interface=1450 (exceeds transit). |
| 20:05:00 | Cilium CNI configuration updated across cluster setting `cni.mtu: 1350`. |
| 20:15:40 | Spark shuffle rerun completes without errors; full MTU path validation harness integrated into CI. |

---

## Terminal & Diagnostic Artifacts

### 1. Spark Executor Shuffle Failure Logs
```console
2026-09-01 19:31:40,192 WARN [TransportChannelHandler] Exception in connection from node-s34-w08.lakehouse/10.244.8.42:7337
java.io.IOException: Connection reset by peer
	at sun.nio.ch.FileDispatcherImpl.read0(Native Method)
	at sun.nio.ch.SocketDispatcher.read(SocketDispatcher.java:39)
	at org.apache.spark.network.util.TransportFrameDecoder.channelRead(TransportFrameDecoder.java:79)
2026-09-01 19:31:40,205 ERROR [ShuffleBlockFetcherIterator] Failed to fetch block shuffle_0_14_89: Connection reset
org.apache.spark.shuffle.FetchFailedException: Failed to connect to node-s34-w08:7337
```

### 2. Live Packet Capture Showing MTU Bottleneck (Tcpdump)
```console
# tcpdump -nnvv -i eth0 'tcp port 7077 or icmp'
14:02:11.109283 IP 10.244.2.14.7077 > 10.244.5.22.42100: Flags [.], seq 1:1440, ack 1, win 502, length 1440
14:02:11.109312 IP 10.244.2.14 > 10.244.5.22: ICMP 10.244.2.14 unreachable - need to frag (mtu 1420), length 556
14:02:11.109350 IP 10.244.2.14.7077 > 10.244.5.22.42100: Flags [F.], seq 1441, ack 1, win 502, length 0
14:02:11.109401 IP 10.244.5.22.42100 > 10.244.2.14.7077: Flags [R], seq 1, win 0, length 0
```

### 3. Cilium eBPF Drop Monitor Trace
```console
# cilium monitor --type drop -v
xx drop (Invalid packet size) flow 0x98f4b to-endpoint 812, identity 4819->1204, cpu 3: 10.244.8.42:7337 -> 10.244.3.18:48922 tcp ACK, length 1472
   Packet size 1522 exceeds device MTU 1450
   Drop reason: Packet size exceeds MTU and DF flag is set
   Final verdict: DROP (Reason: MTU exceeded, ICMP unreach suppressed by policy)

# cilium-dbg bpf tunnel list
TUNNEL          ENDPOINT   PREFIX      ENCAP   MTU
10.244.8.42     ep-812     10.244.8/24 geneve  1450  [MISMATCH: Transit Path=1420]
```

---

## Root Cause Analysis
1. **MTU Stacking Overhead**:
   - Physical NIC MTU: 1500 bytes.
   - Cross-site WireGuard transit encapsulation: -80 bytes (Path MTU = 1420 bytes).
   - Istio Ambient / Cilium Geneve overlay: -50 bytes (Available Pod payload = 1370 bytes).
   - The cluster pod MTU was defaulted to 1450 bytes.
2. **Path MTU Discovery (PMTUD) Blackholing**:
   - Intermediate perimeter firewalls were configured to block inbound ICMP Type 3 Code 4 (`Fragmentation Needed`) packets per an overly aggressive legacy security profile.
   - Consequently, sending sockets never received PMTUD notifications and continued transmitting 1450-byte frames with `DF=1`.

---

## Corrective & Preventative Actions
1. **Fleetwide MTU Standardization**:
   - Standardized Cilium pod MTU to `1350` bytes across all 50 clusters, providing a 70-byte safety buffer under the most aggressive multi-layer encapsulation.
2. **ICMP Type 3 Filtering Correction**:
   - Updated security group baselines to permit ICMP Type 3 Code 4 across inter-site VPC peered networks.
3. **Automated MTU Probe Tooling**:
   - Implemented `scripts/validate_cni_mtu.py` to continuously verify MTU headroom under max payload sizes.
