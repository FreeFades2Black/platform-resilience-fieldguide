import os
import json
import yaml
import pytest
import subprocess

BASE_DIR = os.path.dirname(os.path.dirname(__file__))

def test_incident_postmortems_structure():
    incidents_dir = os.path.join(BASE_DIR, "docs", "incidents")
    files = [f for f in os.listdir(incidents_dir) if f.endswith(".md")]
    assert len(files) == 4, f"Expected 4 incident post-mortems, found {len(files)}"

    required_sections = [
        "Executive Summary",
        "Timeline of Events",
        "Terminal & Diagnostic Artifacts",
        "Root Cause Analysis",
        "Corrective & Preventative Actions"
    ]

    for f in files:
        path = os.path.join(incidents_dir, f)
        with open(path, "r", encoding="utf-8") as file:
            content = file.read()
            for sec in required_sections:
                assert sec in content, f"File {f} missing required RCA section '{sec}'"

def test_runbooks_structure():
    runbooks_dir = os.path.join(BASE_DIR, "runbooks")
    files = [f for f in os.listdir(runbooks_dir) if f.endswith(".md")]
    assert len(files) == 3, f"Expected 3 operational runbooks, found {len(files)}"

    expected_files = [
        "01-triage-lakehouse-ingest-lag.md",
        "02-recovering-stuck-spark-driver-pods.md",
        "03-disconnected-registry-mirroring.md"
    ]
    for ef in expected_files:
        assert ef in files, f"Missing expected runbook {ef}"

def test_prometheus_rules_syntax_and_labels():
    rule_path = os.path.join(BASE_DIR, "monitoring", "prometheus", "lakehouse_sre_rules.yaml")
    assert os.path.exists(rule_path)
    with open(rule_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    
    assert data["apiVersion"] == "monitoring.coreos.com/v1"
    assert data["kind"] == "PrometheusRule"
    groups = data["spec"]["groups"]
    assert len(groups) > 0
    rules = groups[0]["rules"]
    assert len(rules) == 6, f"Expected 6 alerting rules, found {len(rules)}"

    alert_names = [r["alert"] for r in rules]
    assert "LakehouseKafkaConsumerLagCritical" in alert_names
    assert "TrinoCoordinatorMemorySaturation" in alert_names
    assert "CSIVolumeAttachTimeoutExceeded" in alert_names

    for rule in rules:
        assert "expr" in rule
        assert "severity" in rule["labels"]
        assert "summary" in rule["annotations"]
        assert "runbook_url" in rule["annotations"]

def test_grafana_dashboard_json_validity():
    dashboard_path = os.path.join(BASE_DIR, "monitoring", "grafana", "lakehouse_sre_dashboard.json")
    assert os.path.exists(dashboard_path)
    with open(dashboard_path, "r", encoding="utf-8") as f:
        dash = json.load(f)

    assert dash["uid"] == "lakehouse-sre-cockpit"
    assert len(dash["panels"]) >= 5
    for panel in dash["panels"]:
        assert "title" in panel
        assert "targets" in panel
        assert "gridPos" in panel

def test_adrs_structure():
    adr_dir = os.path.join(BASE_DIR, "docs", "adr")
    files = [f for f in os.listdir(adr_dir) if f.endswith(".md")]
    assert len(files) == 2, f"Expected 2 ADRs, found {len(files)}"
    
    for f in files:
        with open(os.path.join(adr_dir, f), "r", encoding="utf-8") as file:
            content = file.read()
            assert "Context and Problem Statement" in content
            assert "Options Considered" in content
            assert "Decision Outcome" in content
            assert "Consequences" in content

def test_lease_pruner_script_cli():
    script_path = os.path.join(BASE_DIR, "scripts", "lease_pruner.py")
    res = subprocess.run(["python", script_path, "--namespace", "lakehouse-compute", "--check-only", "--json"],
                         capture_output=True, text=True)
    assert res.returncode == 0, f"Script failed: {res.stderr}"
    data = json.loads(res.stdout)
    assert data["dry_run"] is True
    assert "lease_status" in data
    assert "deadlocked_pods" in data
    assert len(data["deadlocked_pods"]) > 0

def test_validate_cni_mtu_script():
    script_path = os.path.join(BASE_DIR, "scripts", "validate_cni_mtu.py")
    # Test valid MTU (1350)
    res = subprocess.run(["python", script_path, "--mtu", "1350", "--json"], capture_output=True, text=True)
    assert res.returncode == 0, f"Valid MTU failed: {res.stderr}"
    data = json.loads(res.stdout)
    assert data["status"] == "PASSED"

    # Test invalid exceeding MTU (1480)
    res_fail = subprocess.run(["python", script_path, "--mtu", "1480", "--json"], capture_output=True, text=True)
    assert res_fail.returncode == 1, "Exceeding MTU should return exit code 1"

def test_dockerfile_and_packaging():
    df = os.path.join(BASE_DIR, "Dockerfile")
    req = os.path.join(BASE_DIR, "scripts", "requirements.txt")
    pkg = os.path.join(BASE_DIR, ".github", "workflows", "package-oci.yml")
    assert os.path.exists(df)
    assert os.path.exists(req)
    assert os.path.exists(pkg)
    with open(df, "r", encoding="utf-8") as f:
        content = f.read()
    assert "FROM cgr.dev/chainguard/python:latest-dev AS builder" in content
    assert "USER 65532:65532" in content

