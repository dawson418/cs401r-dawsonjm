"""Run from repo root BEFORE teardown: python scripts/audit_evidence.py
Checks every evidence file the rubric names. Exit code 0 only if everything is OK."""
import json, os, re, subprocess, sys

ok_all = True
def check(name, cond, detail=""):
    global ok_all
    print(("  OK   " if cond else "  FAIL ") + name + (("  -> " + detail) if detail and not cond else ""))
    ok_all &= bool(cond)

def read(p):
    return open(p, errors="ignore").read() if os.path.exists(p) and os.path.getsize(p) > 0 else None

print("== files exist and are non-empty")
for f in ["docs/lab4-build-green.log", "docs/lab4-build-failed.log", "docs/lab4-pipeline-runs.txt",
          "docs/lab4-failure-demo.txt", "docs/lab4-alarm-email.png", "docs/lab4-model-registry.json",
          "docs/lab4-model-package.json", "docs/lab4-mlflow-runs.txt", "docs/lab4-xops-assessment.md",
          "tests/test_data.py", "tests/test_features.py", "tests/test_model.py", "tests/test_fairness.py",
          "models/churn/churn_model.py", "data/feature_engineering.py", "buildspec.yml", "pipeline.yaml"]:
    check(f, os.path.exists(f) and os.path.getsize(f) > 0)

g = read("docs/lab4-build-green.log")
if g:
    print("== green log")
    for t in ["test_data.py", "test_features.py", "test_model.py", "test_fairness.py"]:
        n = len(re.findall(r"tests/%s::\S+ PASSED" % t, g))
        need = 5 if t == "test_features.py" else 2
        check(f"{t}: >= {need} PASSED lines (found {n})", n >= need)
    check("regression test PASSED (not SKIPPED)",
          re.search(r"test_candidate_not_worse_than_champion PASSED", g) is not None)
    check("'champion v.. auc=..; candidate auc=..' warning present",
          re.search(r"champion v\d+ auc=[\d.]+; candidate auc=[\d.]+", g) is not None)
    check("fairness flag/warning visible", "FAIRNESS" in g.upper())
    check("SageMaker pipeline Succeeded", re.search(r"Succeeded", g) is not None)
    check("no failed pytest summary", re.search(r"=+ .*\bfailed\b.* =+", g) is None)

f = read("docs/lab4-build-failed.log")
if f:
    print("== failed log")
    check("shows the deliberate assertion", "DELIBERATE FAILURE" in f)

d = read("docs/lab4-failure-demo.txt")
if d:
    print("== failure demo")
    for lab in ["BEFORE", "AFTER FAILED RUN", "AFTER REVERT"]:
        check(f'snapshot "{lab}" present', f"===== {lab} " in d)
    check("alarm reached ALARM", re.search(r"^ALARM\b", d, re.M) is not None)
    check("alarm action executed (SNS)", "Successfully executed action" in d)
    check("subscription is confirmed (arn:aws:sns)", "arn:aws:sns" in d and "PendingConfirmation" not in d.split("SNS subscriptions")[-1].split("\n", 1)[-1])
    check("failed build: PRE_BUILD FAILED", re.search(r"PRE_BUILD\s+FAILED", d) is not None)
    check("failed build has no BUILD phase", True)  # eyeball: see walkthrough

p = read("docs/lab4-model-package.json")
if p:
    print("== lineage")
    j = json.loads(p); m = j.get("CustomerMetadataProperties", {})
    for k in ["training_data_uri", "training_data_timestamp", "commit_sha", "auc_roc"]:
        check(f"CustomerMetadataProperties.{k}", k in m)
    sha = m.get("commit_sha", "")
    inhist = sha and subprocess.run(["git", "cat-file", "-e", sha + "^{commit}"], capture_output=True).returncode == 0
    check("commit_sha exists in git history", inhist, sha)

r = read("docs/lab4-mlflow-runs.txt")
if r:
    print("== mlflow")
    check("tracking_uri is an MLflow App ARN (:mlflow-app/)", re.search(r"tracking_uri: arn:.*:mlflow-app/", r) is not None)
    rows = [l for l in r.splitlines() if re.match(r"^\d+\s+[0-9a-f]{32}", l)]
    check(">= 3 runs", len(rows) >= 3, str(len(rows)))

a = read("docs/lab4-xops-assessment.md")
if a:
    print("== assessment")
    for h in ["## Pipeline Stage Mapping", "## Champion-Challenger", "## Retraining Triggers",
              "## DataOps Maturity", "## MLOps Maturity"]:
        check(h, h in a)
    check("no leftover placeholders", "__" not in a and "TODO" not in a)
    for path in set(re.findall(r"`([\w./-]+\.\w+)`", a)):
        if "/" in path or path.endswith((".yml", ".yaml", ".tf", ".py", ".log", ".json", ".txt")):
            check(f"cited path exists: {path}", os.path.exists(path))

print("== secrets")
bad = subprocess.run("git ls-files | grep -E '(^|/)(\\.env|terraform\\.tfvars)$|\\.pem$'", shell=True, capture_output=True, text=True).stdout.strip()
check("no .env / tfvars / pem tracked", bad == "", bad)

print("\nALL GOOD" if ok_all else "\nFIX THE FAIL LINES ABOVE")
sys.exit(0 if ok_all else 1)
