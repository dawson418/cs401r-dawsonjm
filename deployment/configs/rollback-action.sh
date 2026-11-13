#!/usr/bin/env bash
# Rollback: send all traffic to champion, canary weight 0. Takes ~90 s; instances keep billing until the endpoint is deleted.
set -euo pipefail
aws sagemaker update-endpoint-weights-and-capacities --endpoint-name northstar-churn-prod \
  --desired-weights-and-capacities VariantName=champion,DesiredWeight=1 VariantName=canary,DesiredWeight=0
