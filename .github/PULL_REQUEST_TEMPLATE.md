## SRE Operational & Resilience Change Request

### Summary of Change
<!-- Provide a concise description of the failure scenario, runbook update, or monitoring adjustment. -->

### Failure Domain & Resilience Impact
- [ ] Incident RCA / Post-Mortem documented under `docs/incidents/`
- [ ] Runbook created or updated under `runbooks/` with deterministic triage steps
- [ ] Prometheus alerting rule (`PrometheusRule`) updated or verified with simulated alerts
- [ ] Grafana operational dashboard updated with Golden Signal metrics
- [ ] Architecture Decision Record (ADR) added under `docs/adr/` if architectural design shifted

### Production Readiness Checklist
- [ ] Runbook validated in simulated environment / lab cluster
- [ ] Remediation scripts run safely in `--check-only` (dry-run) mode by default
- [ ] No hardcoded credentials, cluster IPs, or non-anonymized customer telemetry
- [ ] Alerting rules include runbook annotations and clear severity tiers (`critical`, `warning`, `info`)
- [ ] Automated test suite passing (`make test`)
