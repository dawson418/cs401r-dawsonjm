"""Adds iam:PassRole (and training-job support perms if missing) to the MLEngineer policy."""
import sys

p = sys.argv[1]
L = open(p).read().split("\n")
text = "\n".join(L)

idx = [i for i, l in enumerate(L) if "sagemaker:*" in l]
if not idx:
    sys.exit("no 'sagemaker:*' line found in %s; send the file to Claude" % p)
i = idx[0]
res = [j for j in range(i, -1, -1) if L[j].lstrip().startswith("resource ")]
if not res or "ml_engineer" not in L[res[0]]:
    sys.exit("line %d is not inside the ml_engineer policy (%s); send the file to Claude"
             % (i + 1, L[res[0]].strip() if res else "no resource"))
s = i
while s > 0 and L[s].strip() != "{":
    s -= 1
    if i - s > 12:
        sys.exit("could not find the start of the statement containing sagemaker:*")
ind = L[s][:len(L[s]) - len(L[s].lstrip())]

blocks = []
if "PassSelfToSageMaker" not in text:
    blocks.append([
        "{", '  Sid       = "PassSelfToSageMaker"', '  Effect    = "Allow"',
        '  Action    = ["iam:PassRole"]', "  Resource  = aws_iam_role.ml_engineer.arn",
        '  Condition = { StringEquals = { "iam:PassedToService" = "sagemaker.amazonaws.com" } }', "},"])
if "ecr:" not in text:
    blocks.append([
        "{", '  Sid      = "TrainingJobSupport"', '  Effect   = "Allow"',
        '  Action   = ["ecr:GetAuthorizationToken", "ecr:BatchCheckLayerAvailability", "ecr:GetDownloadUrlForLayer",'
        ' "ecr:BatchGetImage", "logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents",'
        ' "logs:DescribeLogStreams", "cloudwatch:PutMetricData"]',
        '  Resource = "*"', "},"])
if not blocks:
    print("already patched; nothing to do")
    sys.exit(0)
new = [ind + ln for b in blocks for ln in b]
L[s:s] = new
open(p, "w").write("\n".join(L))
print("inserted %d statement(s) before line %d" % (len(blocks), s + 1))
