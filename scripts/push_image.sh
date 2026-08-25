#!/usr/bin/env bash
# Build a service's image and push it to ECR. docs/INFRA.md step 2.
#
#   scripts/push_image.sh api [--no-build]
#
# Tags every push twice: the short commit sha, and `latest`. The sha is what a task
# definition should pin — `latest` is convenient and tells you nothing about what is
# actually running, which is the thing you want to know during an incident.
#
# Refuses to push a dirty tree by default, for the same reason: a tag naming a commit
# whose contents were never that commit is worse than no tag.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

service="${1:-}"
case "$service" in
  api | executor | web) ;;
  *)
    echo "usage: $0 {api|executor|web} [--no-build]" >&2
    exit 1
    ;;
esac

region="${AWS_REGION:-$(aws configure get region)}"
account="$(aws sts get-caller-identity --query Account --output text)"
registry="${account}.dkr.ecr.${region}.amazonaws.com"
repository="interview-helper/${service}"
uri="${registry}/${repository}"

if [[ -n "$(git status --porcelain)" && "${ALLOW_DIRTY:-0}" != "1" ]]; then
  echo "push_image: the tree is dirty, so a commit-sha tag would be a lie." >&2
  echo "            Commit first, or: ALLOW_DIRTY=1 $0 $service" >&2
  exit 1
fi
sha="$(git rev-parse --short HEAD)"

# Created on first push rather than assumed. `scanOnPush` is free and reports known CVEs
# in the image's OS packages, which is the only vulnerability scanning this project has.
if ! aws ecr describe-repositories --repository-names "$repository" --region "$region" >/dev/null 2>&1; then
  echo "push_image: creating ecr repository $repository"
  aws ecr create-repository \
    --repository-name "$repository" \
    --region "$region" \
    --image-scanning-configuration scanOnPush=true >/dev/null
fi

if [[ "${2:-}" != "--no-build" ]]; then
  docker compose -f infra/compose/docker-compose.yml --profile stack build "$service"
fi

aws ecr get-login-password --region "$region" | docker login --username AWS --password-stdin "$registry"

# Braces are load-bearing under zsh: `$uri:latest` triggers the `:l` *lowercase modifier*
# and pushes to `…/apiatest`, which fails with "repository does not exist" and reads like
# a permissions problem. Measured.
docker tag "compose-${service}:latest" "${uri}:${sha}"
docker tag "compose-${service}:latest" "${uri}:latest"
docker push "${uri}:${sha}"
docker push "${uri}:latest"

echo
echo "push_image: ${uri}:${sha}"
echo "            pin the sha in a task definition; 'latest' is for convenience only"
