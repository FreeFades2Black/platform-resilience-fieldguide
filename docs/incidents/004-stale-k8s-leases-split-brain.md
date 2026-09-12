# Incident RCA: Stale Kubernetes Leases & Finalizer Lockouts During Split-Brain Partition

- **Incident ID**: INC-2026-0908-04
- **Severity**: SEV-1 (Control Plane Split-Brain Lockout)
- **Impacted Systems**: Kube-Controller-Manager, CSI Node Driver, Spark Operator Pods
- **Detection Time**: 2026-09-08 08:44:30 UTC
- **Mitigation Time**: 2026-09-08 09:21:12 UTC
- **MTTR**: 36m 42s

---

## Executive Summary
During a transient WAN partition between Edge Data Centers in Site-42 (an air-gapped classified enclave), the Kubernetes control plane lost quorum with two of its five etcd members. Although etcd recovered automatically once network links restored, the leader election `Lease` object for `kube-controller-manager` remained locked by an orphaned leader process that was partitioned into a network blackhole. Pods marked for deletion became indefinitely stuck in `Terminating` state due to unresolved finalizers (`sparkoperator.k8s.io/submission-finalizer` and `kubernetes.io/pvc-protection`), preventing subsequent lakehouse workload scheduling.

---

## Timeline of Events

| Timestamp (UTC) | Event Description |
|---|---|
| 08:44:30 | Upstream BGP flap creates asymmetrical split-brain partition between control plane nodes `cp-01/02` and `cp-03/04/05`. |
| 08:46:10 | Active leader `kube-controller-manager` on `cp-01` cannot renew lease but does not terminate due to SIGKILL timeout. |
| 08:48:00 | WAN partition heals; etcd cluster re-elects leader and reconciles raft state. |
| 08:49:15 | `kube-controller-manager` instance on `cp-03` attempts to acquire lease; blocked by unexpired lease duration lock. |
| 08:52:00 | 45 Spark driver pods scheduled for cleanup remain stuck in `Terminating` status. |
| 08:55:20 | Prometheus alert `KubeLeaseRenewalStalled` triggers page to SRE. |
| 09:02:10 | SRE executes non-destructive lease renewal validation via `scripts/lease_pruner.py --check-only`. |
| 09:08:40 | SRE safely deletes expired lease and clears deadlocked finalizers on completed driver pods. |
| 09:15:00 | `kube-controller-manager` acquires lease and resumes reconciliation loops. |
| 09:21:12 | All terminating pods reaped; lakehouse queue resumes full execution. |

---

## Terminal & Diagnostic Artifacts

### 1. Stalled Lease Status in kube-system
```console
$ kubectl get lease kube-controller-manager -n kube-system -o yaml
apiVersion: coordination.k8s.io/v1
kind: Lease
metadata:
  name: kube-controller-manager
  namespace: kube-system
spec:
  acquireTime: "2026-09-08T06:12:00.182910Z"
  holderIdentity: cp-01.mgmt.site42.mil_9a7b2190
  leaseDurationSeconds: 15
  leaseTransitions: 14
  renewTime: "2026-09-08T08:44:28.910231Z"
```

### 2. Pod Finalizer Deadlock Trace
```console
$ kubectl get pods -n lakehouse-compute -l app.kubernetes.io/name=spark-driver | grep Terminating
spark-etl-batch-0908-01-driver   0/1   Terminating   0   38m
spark-etl-batch-0908-02-driver   0/1   Terminating   0   37m
spark-etl-batch-0908-03-driver   0/1   Terminating   0   35m

$ kubectl get pod spark-etl-batch-0908-01-driver -n lakehouse-compute -o jsonpath='{.metadata.finalizers}'
["sparkoperator.k8s.io/submission-finalizer","kubernetes.io/pvc-protection"]
```

### 3. Controller Manager Split-Brain Logs
```console
$ kubectl logs -n kube-system kube-controller-manager-cp-03.mgmt.site42.mil --tail=30
E0908 08:50:12.189201 leaderelection.go:332] error retrieving resource lock kube-system/kube-controller-manager: lease renewTime has passed but holder has not stepped down
I0908 08:50:14.201382 leaderelection.go:283] failed to acquire lease: cp-01.mgmt.site42.mil_9a7b2190 still holds leader lock
```

---

## Root Cause Analysis
1. **Controller Manager Graceful Shutdown Bug**:
   - The partitioned node had its network interface severed while the process continued running. The lease renew attempt blocked on socket read without a hard socket timeout, preventing the process from cleanly surrendering leadership.
2. **Double Finalizer Interlock**:
   - Spark operator finalizers required an active Spark operator controller to unbind. However, the controller manager was frozen, so the PVC protection controller was also inactive, causing a cyclical deadlock.

---

## Corrective & Preventative Actions
1. **Lease Renewal & Heartbeat Hardening**:
   - Decreased `leader-elect-lease-duration` from 15s to 10s.
   - Configured `leader-elect-renew-deadline` to 8s and `leader-elect-retry-period` to 2s.
2. **Automated Recovery Tooling**:
   - Added automated cleanup capability to `scripts/lease_pruner.py` with safety guards to prune expired leases and dislodge stuck finalizers on terminated jobs.
