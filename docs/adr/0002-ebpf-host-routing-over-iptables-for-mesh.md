# ADR 0002: Cilium eBPF Host Routing Over Kube-Proxy Iptables for Multi-Cluster Data Mesh

- **Status**: Accepted
- **Date**: 2026-09-05
- **Deciders**: Network Infrastructure Team, Lead Platform Security Engineer
- **Context**: Incident `INC-2026-0901-03` (Spark Shuffle Resets and MTU/Connection Tracking Limits)

---

## 1. Context and Problem Statement
Our 50-cluster fleet hosts high-throughput distributed data engines (Apache Spark, Trino, Strimzi Kafka) running alongside Istio service mesh proxies. 

During Spark shuffle exchanges involving hundreds of concurrent tasks, nodes generated over 150,000 ephemeral TCP connections per minute. The standard Linux `kube-proxy` iptables implementation suffered from:
1. Conntrack table exhaustion (`nf_conntrack: table full, dropping packet`).
2. Sequential rule traversal latency: each packet traversed 4,000+ iptables filter rules.
3. High CPU overhead spent in kernel softirq processing network interrupts.

---

## 2. Options Considered

1. **Option A: Scale `nf_conntrack_max` and Maintain Kube-Proxy Iptables**
   - *Pros*: Standard upstream Kubernetes default.
   - *Cons*: Band-aid fix; memory overhead increases linearly, and iptables lock contention (`iptables-restore`) continues causing latency spikes during frequent pod scheduling.
2. **Option B: IPVS Mode for Kube-Proxy**
   - *Pros*: O(1) hash table lookup for service endpoints.
   - *Cons*: Still dependent on Linux netfilter conntrack; does not address sidecar proxy socket acceleration or cross-node overlay overhead.
3. **Option C: Cilium eBPF Direct Host Routing (Selected)**
   - *Pros*: Replaces `kube-proxy` completely; socket-layer eBPF programs bypass TCP/IP stack overhead on local loopback; eBPF map lookups are O(1); direct routing eliminates conntrack bottlenecks.
   - *Cons*: Requires Linux kernel >= 5.10 across all physical cluster nodes; requires team familiarity with eBPF debugging (`cilium-dbg`, `bpftool`).

---

## 3. Decision Outcome
**Selected Option C: Cilium eBPF Direct Host Routing**.
We replaced `kube-proxy` across all 50 clusters with Cilium in eBPF host-routing mode with MTU discovery validation.

### Key Configuration Parameters
```yaml
kubeProxyReplacement: "true"
bpf:
  masquerade: true
  hostRouting: true
tunnel: "geneve"
autoDirectNodeRoutes: true
cni:
  mtu: 1350
```

---

## 4. Consequences
- **Positive**:
  - Spark shuffle throughput increased by 28%.
  - Zero packet drops attributable to conntrack table exhaustion across the fleet.
  - Granular eBPF packet drop monitoring via `cilium monitor --type drop` provides immediate visibility into MTU or policy violations.
- **Negative / Trade-offs**:
  - Nodes must run modernized kernels (Fedora CoreOS / RHEL 9 with 5.14+).
  - SRE on-call engineers must be trained in eBPF tracing tooling.
