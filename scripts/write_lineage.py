"""Write lineage onto a model package: training data URI + timestamp, commit SHA, metrics.
usage: python scripts/write_lineage.py [<package-version-number>]   (default: newest package)
Reads everything from AWS; nothing to type in. Then saves docs/lab4-model-package.json."""
import json, sys
from urllib.parse import urlparse
import boto3

GROUP = "northstar-churn-models"
REGION = "us-east-1"


def find_uri(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "S3Uri" and isinstance(v, str) and v.endswith("evaluation_metrics.json"):
                return v
            r = find_uri(v)
            if r:
                return r
    elif isinstance(node, list):
        for v in node:
            r = find_uri(v)
            if r:
                return r


def run(sm=None, s3=None, version=None, account=None, out="docs/lab4-model-package.json"):
    sm = sm or boto3.client("sagemaker", region_name=REGION)
    s3 = s3 or boto3.client("s3", region_name=REGION)
    account = account or boto3.client("sts").get_caller_identity()["Account"]
    if version:
        arn = f"arn:aws:sagemaker:{REGION}:{account}:model-package/{GROUP}/{version}"
    else:
        arn = sm.list_model_packages(ModelPackageGroupName=GROUP, SortBy="CreationTime",
                                     SortOrder="Descending", MaxResults=1)["ModelPackageSummaryList"][0]["ModelPackageArn"]
    pkg = sm.describe_model_package(ModelPackageName=arn)
    uri = find_uri(pkg.get("ModelMetrics", {}))
    assert uri, "package has no evaluation_metrics.json in ModelMetrics"
    u = urlparse(uri)
    m = json.loads(s3.get_object(Bucket=u.netloc, Key=u.path.lstrip("/"))["Body"].read())
    sha = m["commit_sha"]
    assert sha != "unknown", "commit_sha is 'unknown' - this package was not built by the CodeBuild pipeline"
    data_prefix = "features/customers/"
    newest = None
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=u.netloc, Prefix=data_prefix):
        for o in page.get("Contents", []):
            if newest is None or o["LastModified"] > newest:
                newest = o["LastModified"]
    props = {
        "training_data_uri": f"s3://{u.netloc}/{data_prefix}",
        "training_data_timestamp": newest.isoformat(),
        "commit_sha": sha,
        "auc_roc": f"{m['auc_roc']:.4f}",
        "precision_top10": f"{m['precision_top10']:.4f}",
        "recall_top10": f"{m['recall_top10']:.4f}",
        "lift_ci_low": f"{m['lift_ci_low']:.4f}",
        "lift_ci_high": f"{m['lift_ci_high']:.4f}",
    }
    sm.update_model_package(ModelPackageArn=arn, CustomerMetadataProperties=props)
    desc = sm.describe_model_package(ModelPackageName=arn)
    with open(out, "w") as f:
        json.dump(desc, f, indent=2, default=str)
    print("lineage written to", arn)
    print(json.dumps(desc["CustomerMetadataProperties"], indent=2))
    return desc


if __name__ == "__main__":
    run(version=sys.argv[1] if len(sys.argv) > 1 else None)
