# Infrastructure

> **Status:** **Step 1 built (2026-08-25)** — `make up-stack` runs the whole application
> in containers behind one front door, and the sandbox still isolates from inside one.
> Since 2026-08-29 every Docker target follows a per-machine daemon pin —
> [One daemon per machine](#one-daemon-per-machine) — after a second daemon made the
> data volume vanish from view.
> Steps 2–5 are specification: **no AWS resource exists yet**, and the next one needs an
> authenticated AWS session rather than more code. Nothing before Phase 6 depends on AWS.
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
This project produces three: `api`, `executor`, `web` — **all three have Dockerfiles as of
2026-08-25**. Each is multi-stage, so the runtime image carries the application and not the
toolchain that built it, and the two web-facing ones run as a non-root uid.

**Image / registry.** An image is the built container; a registry is where images are
stored. AWS's registry is **ECR** (Elastic Container Registry). You build locally or in
CI, push to ECR, and AWS pulls from there.

**Docker Compose.** Runs several containers together on one machine, with a network
between them. It is also a *supported deployment* — the intended way the stack runs on
another device, not merely a dev-only convenience. **It now composes five:** `make up-stack` brings up Postgres, `api`, `executor`, `web` and
a `caddy` front door. `make dev` still brings up Postgres alone, because the local
uvicorn/next workflow wants only that.

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

**Step 1 — Compose locally. ✅ Built 2026-08-25.** `make up-stack` brings up Postgres, API,
executor, web and a front door. What it cost is under **What step 1 actually taught**
below — three of the four problems were not the ones this step was expected to teach.

**Step 2 — One service on Fargate, by hand. ← in progress.**
Credentials are live (account `859294994564`, `us-east-2`) and **the API image is in ECR**:
`interview-helper/api`, tagged with the commit sha and `latest`, 113 MB compressed.
`make push SERVICE=api` reproduces it.

The *service* half is deliberately left to a human. INFRA.md's own reason is that the
clicking is what makes the Terraform replacing it legible — and there is a second one now:
a Fargate service bills per second from the moment it starts, so it is a spending decision
rather than a build step.

Two things to know before creating it:

- **The images are `arm64`**, built on Apple Silicon. Fargate runs them natively if the
  task definition sets `runtimePlatform.cpuArchitecture = ARM64`; leave it at the `X86_64`
  default and the task fails to start with an exec-format error. ARM64 is also ~20% cheaper
  per vCPU-hour.
- **`/health` needs no database**, which is what makes a first service cheap: it answers
  before RDS exists, so step 2 can be one task with no load balancer at all. Every
  `/api/v1` route will answer `503` until `SESSION_SECRET` is injected and a database is
  reachable, and that is correct behaviour rather than a broken deploy.

Everything a service needs *except the service* now exists in the account, created with
the CLI because none of it bills: the execution role, a 7-day log group, a security group
opening 8000, the `interview-helper` cluster, and task definition revision 1 pinned to the
image digest. **[`infra/ecs/README.md`](../infra/ecs/README.md) is the console checklist**
— which fields, which values, and the two that are easy to get wrong.

`scripts/aws_teardown.sh` deletes all of it, and exists from the day the first resource
was created rather than the day it was needed. The claim this document makes for IaC —
"you can delete everything and get it back" — is only true if deleting everything is one
command somebody has actually run.

**Step 2 (detail) — One service on Fargate, by hand.** Push the API image to ECR and run a single
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

## What step 1 actually taught

Four problems, and the one this step was *supposed* to be about — how services find each
other on a network — was the least of them.

**The compose project name owns the data.** Adding a tidy `name: interview-helper` renames
the volume with it, so the stack comes up against `interview-helper_postgres_data` while
every session, evidence row and practice problem sits in the orphaned
`compose_postgres_data`. Nothing is deleted and everything looks deleted. There is now no
`name:` key and a comment saying why.

**Debian's Docker packaging moved.** `apt-get install docker.io` on trixie succeeds and
installs **only `docker-init`** — no `/usr/bin/docker`. The build was green and every
execution came back `could not launch docker: [Errno 2] No such file or directory`. The
CLI is now copied from `docker:27-cli`, pinned, which is immune to that drift.

**Next bakes its rewrites at build time.** `next.config.ts` reads `API_ORIGIN` and
`rewrites()` is resolved into `.next/routes-manifest.json` during `next build` — so an
image built on a laptop carries `http://localhost:8000` however the runtime environment is
set. Measured: `API_ORIGIN=http://api:8000` in the container, `localhost:8000` in the
manifest, every proxied request `ECONNREFUSED`. A build arg would have "fixed" it by making
the image environment-specific, which is the opposite of what an image is for.

The fix is the interesting part: **the stack grew a `caddy` front door that routes by
path**, which is the job the ALB does in the diagram below. So compose now mirrors the
target topology rather than approximating it, the image is portable, and the web app's
rewrites are demoted to a `pnpm dev` convenience. Step 5's portability gate got more
meaningful as a side effect.

**Only the front door publishes a port.** `api` and `executor` are reachable only on the
compose network, which is the same boundary private subnets draw in AWS. It also keeps the
session cookie first-party without the web app proxying anything.

### One daemon per machine

The fifth problem arrived four days after the other four, and it is the project-name
lesson again, one level up. **The compose project name decides which volume the data is
in; the daemon decides which volumes exist at all.** This machine grew a second Docker
daemon on 2026-08-27 — Docker Desktop, alongside the colima that had run every
`make up-stack` so far — and `docker` stopped being one thing: each daemon keeps its own
volumes, and the ambient context (which Desktop takes over on install) names the only
one any command can see. The next `make up-stack` followed it to the new daemon, Postgres
initialised an empty `compose_postgres_data` there, and `/jobs` answered 500 over a
missing table while 47 applications sat intact in the other daemon's volume. The third
incident that presented as data loss, and the first with nothing actually lost —
[BUILDLOG](BUILDLOG.md) has the account, [OPERATIONS](OPERATIONS.md#backups) the
recovery.

The choice of daemon is now explicit, in two halves:

- **`.docker-context`** (machine-local, gitignored) names the daemon this checkout's data
  lives on. The Makefile exports it as `DOCKER_CONTEXT`, which every docker and compose
  child honors — the pin decides, not whatever `docker context use` last said.
  `backup_db.sh` reads it directly too, because launchd invokes it without make, and a
  nightly backup on the wrong daemon would faithfully archive an empty database.
- **`scripts/daemon_guard.sh`** fronts every Docker-touching target. With a pin, the
  pinned daemon must answer, and the error says how to start it. Without one it counts
  the *distinct* daemons answering — by daemon ID, because Desktop's `default` and
  `desktop-linux` contexts are one daemon wearing two names — and refuses at two, naming
  the pin as the fix. One reachable daemon passes silently: a fresh machine owes no
  ceremony, which is what step 5's portability gate needs.

The detail worth keeping: nobody has to run anything unusual to hit this. Installing
Docker Desktop is enough — it takes the active context, and every `docker` command
afterwards quietly means a different machine.

### The executor holds the Docker socket, and that is the local model

`apps/executor/Dockerfile` mounts `/var/run/docker.sock`, which is **root-equivalent
control of the host**. It is written down in three places now because it deserves to be:
the executor is a *launcher* that never evaluates candidate code in its own process, it
holds the socket and no other credential, and it does not survive to production —
[ARCHITECTURE](ARCHITECTURE.md#where-the-sandbox-actually-lives) has the Fargate reasoning.

What makes it work at all is that the sandbox passes source on **stdin** and mounts only
`--tmpfs`. A sibling container started through the host daemon needs no path from the
executor's own filesystem, which is exactly what a bind-mounted source would have broken.

Isolation was re-verified from inside the containerised launcher rather than assumed —
same properties the escape suite checks, run against the deployed topology:

```
network egress             DENIED
the docker socket itself   DENIED   ← the sandbox does not inherit its launcher's socket
writing outside /scratch   DENIED
reading /etc/passwd        DENIED
running as root            DENIED
```

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
