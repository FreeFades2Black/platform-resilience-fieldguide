# Operational Runbook: Recovering Stuck Spark Driver Pods & Finalizer Deadlocks

- **Runbook ID**: RB-COMPUTE-002
- **Target Substrates**: Spark on K8s, Spark Operator, Kubernetes Controller Manager
- **Severity Level**: Priority 2

---

## 1. Symptom Description
Spark driver pods remain stuck in `Terminating` state indefinitely. Running `kubectl delete pod` with `--force --grace-period=0` fails to dislodge the pod because Kubernetes blocks deletion until all metadata finalizers have been successfully reconciled.

---

## 2. Automated Safety Pruning

Before taking manual actions, execute the validated `lease_pruner.py` tool in safe dry-run mode:

```console
# Step 1: Run in verification mode (no changes made)
$ python scripts/lease_pruner.py --namespace lakehouse-compute --check-only

# Step 2: Review dry-run output
# Example Output:
# [*] Found 3 pods stuck in Terminating > 10m
# [*] Pod: spark-driver-batch-01 (Finalizers: ['sparkoperator.k8s.io/submission-finalizer'])
# [!] Safe to clear: Pod application status is COMPLETED in Spark history server.

# Step 3: Execute safe automated prune
$ python scripts/lease_pruner.py --namespace lakehouse-compute --prune-finalizers --confirm
```

---

## 3. Manual Fallback Procedure

If automated remediation is unavailable, follow this manual procedure:

### Step 3.1: Verify Driver Completion in History Server
Ensure the Spark job is genuinely terminated and not actively writing shuffle data to remote object storage:
```console
$ curl -s http://spark-history-server.lakehouse-compute:18080/api/v1/applications | jq '.[] | select(.id=="spark-app-id")'
```

### Step 3.2: Inspect Dangling Finalizers
```console
$ kubectl get pod <pod-name> -n lakehouse-compute -o jsonpath='{.metadata.finalizers}'
```

### Step 3.3: Patch Pod to Strip Finalizers
```console
$ kubectl patch pod <pod-name> -n lakehouse-compute -p '{"metadata":{"finalizers":[]}}' --type=merge
```

### Step 3.4: Reap Zombie Executor Pods
```console
$ kubectl delete pods -n lakehouse-compute -l spark-role=executor,spark-app-id=<spark-app-id> --grace-period=0 --force
```
