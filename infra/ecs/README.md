# Step 2 — one service on Fargate, by hand

The scaffolding for [INFRA.md](../../docs/INFRA.md)'s step 2. Everything in this directory
was created with the CLI because none of it costs anything; the **service** is left to be
created by hand, which is what the step is for.

## What already exists in the account

| Resource | Value | Billable |
|---|---|---|
| ECR repository | `interview-helper/api` — tags `854492e`, `latest` | storage only, ~cents |
| Execution role | `ecsTaskExecutionRole` | no |
| Log group | `/ecs/interview-helper-api`, 7-day retention | per GB ingested |
| Security group | `sg-0def3ce0c872e11be`, tcp/8000 from anywhere | no |
| Cluster | `interview-helper` | no, while empty |
| Task definition | `interview-helper-api` (this file) | no |

VPC `vpc-09dc9974fb3b6d3a5` (the default), public subnets in `us-east-2a/b/c`.

## Three things the task definition gets right, that are easy to get wrong

**`cpuArchitecture: ARM64`.** The images are built on Apple Silicon. Leave this at the
`X86_64` default and the task pulls, starts, and dies immediately with an exec-format
error — which surfaces as a service that never stabilises rather than as anything naming
the architecture. ARM64 is also cheaper per vCPU-hour.

**An execution role, and no task role.** The *execution* role is ECS's — it pulls the image
and writes the logs. A *task* role would be the container's own AWS identity, and the API
does not need one yet: it will when it calls Bedrock and reads a secret, and giving it one
before then is a permission nobody is using.

**No `SESSION_SECRET`, deliberately.** Every `/api/v1` route will answer `503` naming the
variable, and `/health` will answer `200` — which is the whole of what step 2 is checking.
The secret belongs in Secrets Manager and injected as `secrets`, not `environment`, and
that arrives with step 4. A service that half-works and says exactly which half is a better
first deploy than one carrying a secret pasted into a task definition.

## Creating the service

Console: **ECS → Clusters → `interview-helper` → Services → Create**

| Field | Value |
|---|---|
| Compute options | Launch type → **FARGATE** |
| Task definition | `interview-helper-api`, latest revision |
| Service name | `api` |
| Desired tasks | **1** |
| Networking → VPC | `vpc-09dc9974fb3b6d3a5` |
| Subnets | any one of the three public ones |
| Security group | **existing** → `interview-helper-api` |
| Public IP | **Turned on** — without it the task cannot reach ECR to pull, and fails with a timeout that reads like a network fault |

Then, from **Tasks → the running task → Configuration**, take the public IP:

```sh
curl http://<public-ip>:8000/health        # {"status":"ok","version":"0.1.0"}
curl -i http://<public-ip>:8000/api/v1/mastery | head -3   # 503, naming SESSION_SECRET
```

Logs land in CloudWatch under `/ecs/interview-helper-api`. Seeing where they land is half
the point of the step.

## Tearing it down

The service is the only part that bills by the second:

```sh
aws ecs update-service --cluster interview-helper --service api --desired-count 0 --region us-east-2
aws ecs delete-service --cluster interview-helper --service api --force --region us-east-2
```

`scripts/aws_teardown.sh` removes everything in the table above.
