# source scripts/lab4_helpers.sh   (from the repo root, bash or zsh)
export AWS_PAGER=""
mkdir -p docs
TOPIC=$(aws cloudformation describe-stacks --stack-name northstar-cicd \
  --query "Stacks[0].Outputs[?OutputKey=='ModelApprovalTopicArn'].OutputValue" --output text)

snap () {   # usage: snap "LABEL"  -> appends a labelled snapshot to docs/lab4-failure-demo.txt
  {
    echo; echo "===== $1  ($(date -u +%Y-%m-%dT%H:%M:%SZ)) ====="
    echo "--- newest CodeBuild build: id, commit, status, then phases"
    B=$(aws codebuild list-builds-for-project --project-name northstar-ci --query 'ids[0]' --output text)
    aws codebuild batch-get-builds --ids "$B" --query 'builds[0].[id,resolvedSourceVersion,buildStatus]' --output text
    aws codebuild batch-get-builds --ids "$B" --query 'builds[0].phases[].[phaseType,phaseStatus]' --output text
    echo "--- newest 3 model packages"
    aws sagemaker list-model-packages --model-package-group-name northstar-churn-models \
      --sort-by CreationTime --sort-order Descending --max-results 3 \
      --query 'ModelPackageSummaryList[].[ModelPackageVersion,ModelApprovalStatus,CreationTime]' --output text
    echo "--- alarm state"
    aws cloudwatch describe-alarms --alarm-names northstar-ci-build-failure \
      --query 'MetricAlarms[0].[StateValue,StateUpdatedTimestamp]' --output text
    echo "--- alarm action history"
    aws cloudwatch describe-alarm-history --alarm-name northstar-ci-build-failure \
      --history-item-type Action --max-records 5 --query 'AlarmHistoryItems[].[Timestamp,HistorySummary]' --output text
    echo "--- SNS subscriptions (an ARN, not PendingConfirmation)"
    aws sns list-subscriptions-by-topic --topic-arn "$TOPIC" --query 'Subscriptions[].[Protocol,SubscriptionArn]' --output text
  } 2>&1 | tee -a docs/lab4-failure-demo.txt
}

save_log () {   # usage: save_log <codebuild-build-id> <output-file>
  read -r G S <<< "$(aws codebuild batch-get-builds --ids "$1" \
      --query 'builds[0].logs.[groupName,streamName]' --output text)"
  aws logs filter-log-events --log-group-name "$G" --log-stream-names "$S" --output json \
    | python3 -c 'import json,sys; sys.stdout.write("".join(e["message"] if e["message"].endswith("\n") else e["message"]+"\n" for e in json.load(sys.stdin)["events"]))' \
    > "$2"
}

newest_build () { aws codebuild list-builds-for-project --project-name northstar-ci --query 'ids[0]' --output text; }
build_status () { aws codebuild batch-get-builds --ids "$(newest_build)" --query 'builds[0].[buildStatus,currentPhase]' --output text; }

wait_build () {   # wait until the newest build finishes; prints final status. usage: wait_build <old-build-id>
  local OLD="$1" B
  while true; do
    B=$(newest_build)
    if [ "$B" != "$OLD" ]; then
      S=$(aws codebuild batch-get-builds --ids "$B" --query 'builds[0].buildStatus' --output text)
      echo "$(date +%H:%M:%S) $B $S"
      [ "$S" != "IN_PROGRESS" ] && break
    else
      echo "$(date +%H:%M:%S) waiting for a new build to start..."
    fi
    sleep 20
  done
}

capture_all () {   # the handout's capture block. usage: capture_all <final-green-build-id>
  {
    echo "===== CodePipeline executions: start, status, commit, execution id ====="
    aws codepipeline list-pipeline-executions --pipeline-name northstar-pipeline \
      --query 'pipelineExecutionSummaries[].[startTime,status,sourceRevisions[0].revisionId,pipelineExecutionId]' --output text
    echo; echo "===== CodeBuild builds, newest first: start, status, commit, build id ====="
    for B in $(aws codebuild list-builds-for-project --project-name northstar-ci --query 'ids[]' --output text); do
      aws codebuild batch-get-builds --ids "$B" --query 'builds[0].[startTime,buildStatus,resolvedSourceVersion,id]' --output text
      aws codebuild batch-get-builds --ids "$B" --query 'builds[0].phases[].[phaseType,phaseStatus]' --output text | sed 's/^/    /'
      save_log "$B" /tmp/lab4-build.log && grep -E '^=+ .*(passed|failed|error)' /tmp/lab4-build.log | sed 's/^/    pytest: /'
    done
    echo; echo "===== SageMaker Pipeline executions: start, status, name ====="
    aws sagemaker list-pipeline-executions --pipeline-name northstar-churn-pipeline \
      --query 'PipelineExecutionSummaries[].[StartTime,PipelineExecutionStatus,PipelineExecutionDisplayName]' --output text
  } 2>&1 | tee docs/lab4-pipeline-runs.txt
  save_log "$1" docs/lab4-build-green.log
  aws sagemaker list-model-packages --model-package-group-name northstar-churn-models \
    --sort-by CreationTime --sort-order Descending --output json > docs/lab4-model-registry.json
}
