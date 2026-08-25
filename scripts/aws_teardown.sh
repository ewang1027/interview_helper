#!/usr/bin/env bash
# Delete every AWS resource Phase 6 created. docs/INFRA.md.
#
#   scripts/aws_teardown.sh [--keep-images]
#
# Exists from the first day anything was created, not from the day it was needed. The
# argument for infrastructure-as-code that INFRA.md makes — "you can delete everything and
# get it back" — is only true if deleting everything is one command somebody has run.
#
# Ordered by dependency: the service holds the tasks, the tasks hold the ENI that pins the
# security group, and the log group outlives all of it.
set -uo pipefail

REGION="${AWS_REGION:-us-east-2}"
CLUSTER=interview-helper
SERVICE=api
LOG_GROUP=/ecs/interview-helper-api
SG_NAME=interview-helper-api

say() { printf '  %-46s %s\n' "$1" "$2"; }

echo "tearing down in $REGION"

# 1. The service — the only thing here that bills by the second.
if aws ecs describe-services --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION" \
  --query 'services[0].status' --output text 2>/dev/null | grep -qv '^\(None\|INACTIVE\)$'; then
  aws ecs update-service --cluster "$CLUSTER" --service "$SERVICE" --desired-count 0 --region "$REGION" >/dev/null 2>&1
  aws ecs delete-service --cluster "$CLUSTER" --service "$SERVICE" --force --region "$REGION" >/dev/null 2>&1
  say "service $SERVICE" "deleted"
  # The task's network interface is released asynchronously, and the security group cannot
  # go while it holds one. Waiting here is what stops the SG deletion below failing with a
  # DependencyViolation that looks like a permissions problem.
  aws ecs wait services-inactive --cluster "$CLUSTER" --services "$SERVICE" --region "$REGION" 2>/dev/null
  sleep 20
else
  say "service $SERVICE" "absent"
fi

# 2. Task definitions — deregistering is free either way, but leaving dozens of revisions
#    behind makes the console unreadable.
for arn in $(aws ecs list-task-definitions --family-prefix interview-helper-api --region "$REGION" --query 'taskDefinitionArns[]' --output text 2>/dev/null); do
  aws ecs deregister-task-definition --task-definition "$arn" --region "$REGION" >/dev/null 2>&1
  say "task definition" "$(basename "$arn") deregistered"
done

# 3. Cluster.
if aws ecs delete-cluster --cluster "$CLUSTER" --region "$REGION" >/dev/null 2>&1; then
  say "cluster $CLUSTER" "deleted"
else
  say "cluster $CLUSTER" "absent or not empty"
fi

# 4. Security group.
SG=$(aws ec2 describe-security-groups --region "$REGION" \
  --filters "Name=group-name,Values=$SG_NAME" --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null)
if [[ -n "$SG" && "$SG" != "None" ]]; then
  if aws ec2 delete-security-group --group-id "$SG" --region "$REGION" >/dev/null 2>&1; then
    say "security group $SG" "deleted"
  else
    say "security group $SG" "still in use — retry in a minute"
  fi
else
  say "security group" "absent"
fi

# 5. Log group. Deleting it destroys the logs, which is the point of a teardown.
if aws logs delete-log-group --log-group-name "$LOG_GROUP" --region "$REGION" >/dev/null 2>&1; then
  say "log group $LOG_GROUP" "deleted"
else
  say "log group" "absent"
fi

# 6. ECR. Kept by default: the images cost cents and rebuilding them is the slow part of
#    getting back to where you were.
if [[ "${1:-}" == "--keep-images" ]]; then
  say "ecr repository" "kept (--keep-images)"
else
  if aws ecr delete-repository --repository-name interview-helper/api --force --region "$REGION" >/dev/null 2>&1; then
    say "ecr interview-helper/api" "deleted"
  else
    say "ecr repository" "absent"
  fi
fi

# 7. The execution role is shared by every ECS task in the account and is *not* removed
#    here. Deleting a role something else assumes is a failure that shows up later, in
#    another project, as a task that will not start.
say "ecsTaskExecutionRole" "left alone (account-wide, may be shared)"

echo
echo "done. 'aws ecs list-services --cluster $CLUSTER --region $REGION' should be empty."
