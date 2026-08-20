# Infrastructure

> **Status:** Specification and learning ramp — no AWS resource exists yet. Lands in
> **Phase 6**. Nothing before Phase 6 depends on AWS; the app runs under Docker Compose.
> Related: [SECURITY](SECURITY.md) (what these controls enforce) · [OPERATIONS](OPERATIONS.md) (running it once deployed) · [COST](COST.md) · [GLOSSARY](GLOSSARY.md#infrastructure)

This file is written to **teach**, not just to specify. Phase 6 is as much a cloud-infra
learning exercise as a deployment, so each concept is explained before it is used, and
each Terraform module carries its own README saying what the resource is and why it
exists.

If you already know this material, the summary is: Docker Compose for portability,
Terraform + ECS Fargate behind an ALB for AWS, RDS Postgres, Secrets Manager, CloudWatch,
Budgets alarm.

---

## The vocabulary, in order

**Container.** A packaged filesystem plus the command to run. It bundles your code *and*
its dependencies, so the same artifact behaves identically on your laptop and in AWS.
This project **will produce** three: `api`, `executor`, `web`. **None has a Dockerfile
yet** — they are built in Phase 6.

**Image / registry.** An image is the built container; a registry is where images are
stored. AWS's registry is **ECR** (Elastic Container Registry). You build locally or in
CI, push to ECR, and AWS pulls from there.

**Docker Compose.** Runs several containers together on one machine, with a network
between them. It is also a *supported deployment* — the intended way the stack runs on
another device, not merely a dev-only convenience. **Today it composes one service:**
`make dev` brings up Postgres alone, because `api`, `web` and `executor` have no
Dockerfiles yet. The other three join in Phase 6, which is when the portability claim
above becomes testable.

**ECS (Elastic Container Service).** AWS's container orchestrator. You tell it "run 2
copies of this image, with this much CPU and memory"; it does that and restarts them
when they die.

**Fargate.** A *mode* of ECS. Normally you would rent EC2 virtual machines, patch their
operating systems, and manage capacity. Fargate skips that: AWS runs the container
without you owning a server. You pay per vCPU-second and GB-second of container runtime.
"ECS Fargate" therefore means: AWS orchestrates my containers, and I never touch a VM.

**Task / service.** A **task** is one running set of containers. A **service** keeps N
tasks alive and replaces unhealthy ones. Three services here: `api`, `executor`, `web`.

**VPC (Virtual Private Cloud).** Your private network in AWS. Split into **subnets**:
- *public* subnets can reach the internet directly — the load balancer lives here.
- *private* subnets cannot be reached from the internet — the API, executor, and
  database live here. This is the main security boundary in the whole design.

**ALB (Application Load Balancer).** The public front door. It terminates HTTPS, checks
container health, and forwards traffic to whichever tasks are healthy. It lives in the
public subnets and is the only thing with a public address.

**Security group.** A per-resource firewall. The executor's security group will allow
inbound traffic *only* from the API and permit **no outbound traffic at all** — which is
how "the sandbox has no network" is enforced at the infrastructure layer rather than
only in code.

**RDS.** Managed Postgres — AWS handles backups, patching, and failover.

**Secrets Manager.** Where the database password, API keys, `SESSION_SECRET` and
`GITHUB_CLIENT_SECRET` live. Containers receive them as environment variables injected at
task start, so no secret is ever baked into an image or committed. Two consequences for
the API task: it must start with `SESSION_SECRET` set or every `/api/v1` route answers
`503` ([API.md](API.md#auth)), and `GITHUB_REDIRECT_URI` must match the OAuth app's
registered callback for the deployed hostname rather than localhost.

**IAM (Identity and Access Management).** Who may do what. Each service gets a **task
role** granting only what it needs. The API may call Bedrock and read one secret; the
executor may do neither.

**Terraform / IaC.** Your infrastructure written as files instead of console clicks.
`terraform plan` shows what would change; `terraform apply` makes it so. The value is
that the infrastructure is reviewable, diffable, and rebuildable — and that you can
delete everything and get it back.

---

## The learning ramp (Phase 6, in order)

Each step is understood before the next begins.

**Step 1 — Compose locally.** `docker compose up` brings up Postgres, API, executor, and
web. Goal: see what a container is and how services find each other on a network.
*Nothing AWS yet.*

**Step 2 — One service on Fargate, by hand.** Push the API image to ECR and run a single
Fargate service through the console. Goal: watch a container you built serve real traffic
from AWS, and see where the logs land. Clicking through the console once makes the
Terraform that replaces it legible.

**Step 3 — Terraform that one service.** Reproduce step 2 in code, destroy the manual
version, `terraform apply`. Goal: see IaC replace clicking, and see `plan` tell you what
will change before it changes.

**Step 4 — The rest of the stack.** VPC with public/private subnets, ALB + ACM
certificate + Route53 record, RDS, Secrets Manager, CloudWatch log groups and alarms,
Budgets alarm on the credits. Added incrementally, each with a `plan` read before
`apply`.

**Step 5 — Portability check.** `docker compose up` on a second device, against the same
images. This is a gate, not a nice-to-have.

---

## Target architecture

```
                    Internet
                       │
                   Route53  (DNS)
                       │
                    ACM cert
                       │
              ┌────────▼────────┐
              │       ALB       │   public subnets
              └────────┬────────┘
        ┌──────────────┼──────────────┐
        │              │              │      private subnets
   ┌────▼────┐   ┌─────▼─────┐  ┌─────▼─────┐
   │   web   │   │    api    │  │ executor  │   ECS Fargate services
   └─────────┘   └─────┬─────┘  └───────────┘
                       │              ▲  no egress at all
                 ┌─────▼─────┐        │  ingress only from api
                 │    RDS    │────────┘
                 │ Postgres  │   private subnets
                 └───────────┘
```

## Terraform module layout

Each directory gets a README explaining its resources in the vocabulary above.

| Module | Contains |
|---|---|
| `network/` | VPC, subnets, route tables, NAT, security groups |
| `data/` | RDS Postgres, subnet group, parameter group, Secrets Manager entries |
| `ecs/` | Cluster, task definitions, services, ECR repos, task roles, ALB, target groups |
| `observability/` | CloudWatch log groups, metric alarms, AWS Budgets |

## Cost posture

Fargate bills per vCPU-second and GB-second, so idle services still cost money. With
$10k in credits this is comfortable, but the Budgets alarm exists so "comfortable" stays
a measured claim rather than an assumption. Bedrock spend is tracked separately in
[`COST.md`](COST.md).

Decisions deliberately deferred to Phase 6, to be made against real numbers:
- Aurora Serverless v2 vs. plain RDS Postgres.
- Whether `web` needs to be a Fargate service at all, or should be static hosting.
- NAT gateway vs. VPC endpoints for pulling images into private subnets — NAT is simpler
  and meaningfully more expensive.
