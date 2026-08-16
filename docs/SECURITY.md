# Security

> **Status:** Threat model and test specification — the executor itself is not built.
> Isolation lands in **Phase 2**; AWS-layer enforcement in **Phase 6**.
> Related: [ARCHITECTURE](ARCHITECTURE.md) (service boundaries) · [INFRA](INFRA.md) (where these controls are configured) · [GRADING](GRADING.md) (what the executor is for)

## Being honest about the threat model

This is a single-user application. There is no hostile user population, no tenant
isolation problem, and no attacker with an incentive to pivot through it. Writing a
threat model that pretends otherwise produces security theatre.

The **real** threats, in order of likelihood:

| # | Threat | Why it is real |
|---|---|---|
| 1 | **Accidentally destructive code** — a solution with a runaway loop, a fork bomb, or a stray `rm` | You will write bad code on purpose; that is the point of practice |
| 2 | **LLM-generated code executing** | The interviewer agent can run code. Model output is not reviewed before execution |
| 3 | **Prompt injection through corpus content** | Corpus statements are researched from the open web and land inside prompts |
| 4 | **Credential exposure** | AWS credentials, a Bedrock-capable role, and a database password all exist in this system |
| 5 | **Public repo leakage** | The repo is public; anything committed is permanent |

Threats 1 and 2 are near-certain. Threat 4 is the one with real blast radius — a leaked
Bedrock role against $10k of credits is the worst realistic outcome here, and it is worth
more attention than sandbox exotica.

## Trust boundaries

```
   browser ─────▶ api ─────▶ executor
  untrusted    TRUSTED      HOSTILE
   input       (creds)     (no creds)
                  │
                  ▼
              postgres
              bedrock
```

The single most valuable property in the design: **the process that runs untrusted code
and the process that holds the database password are never the same process.** The
executor has no DB client, no model client, no secrets, and no outbound network. If it is
fully compromised, the attacker has a container that can compute and nothing else.

This is why `apps/executor/pyproject.toml` lists FastAPI, uvicorn, and Pydantic and
nothing else. Every dependency there is attack surface with no compensating benefit.

## Defence in depth for the executor

Six layers, each independently sufficient to prevent a class of harm:

| Layer | Control | Blocks |
|---|---|---|
| Network | No egress. Enforced by Docker network config locally and a security group with **no outbound rules** in AWS | Exfiltration, callbacks, dependency fetching |
| Filesystem | Read-only root; one writable `tmpfs` scratch dir per execution, destroyed after | Persistence, cross-execution contamination |
| Identity | Runs as a non-root user with no shell | Privilege escalation |
| Capabilities | All Linux capabilities dropped; `no-new-privileges` | Kernel-adjacent tricks |
| Syscalls | Default seccomp profile, plus explicit deny for `mount`, `ptrace`, `unshare`, socket families | Sandbox escape primitives |
| Resources | Wall-clock timeout, memory cap, PID cap, CPU quota | Denial of service against the host |

Isolation is at the **infrastructure** layer, not in code. "The sandbox has no network" is
a security group with zero egress rules — not a Python check that can be bypassed by the
code it is checking.

## The five escape tests

Phase 2's gate. Each **must fail closed** — the attempt fails, the service survives, and
the failure is reported as a grading failure rather than a crash. They live in
`apps/executor/tests`, marked `sandbox`, and run in CI.

| # | Test | Attempt | Required outcome |
|---|---|---|---|
| 1 | `test_no_network_egress` | DNS resolve, raw socket connect, and an HTTP GET to a public address | All three fail; execution returns a normal failed result |
| 2 | `test_no_filesystem_escape` | Read `/etc/passwd`, read outside the scratch dir, write outside the scratch dir, traverse with `../` | Reads outside scratch denied; writes outside denied |
| 3 | `test_pid_exhaustion` | Fork bomb | Killed at the PID cap; **the executor service still answers `/health`** |
| 4 | `test_memory_bomb` | Allocate past the memory cap | OOM-killed; service survives; result reports the limit that was hit |
| 5 | `test_wall_clock_timeout` | Infinite loop | Killed at the timeout; result reports a timeout, not a hang |

Plus a sixth that is not an escape but is the one most likely to produce silently wrong
grades:

| 6 | `test_no_cross_execution_contamination` | Write a file, then run a second execution that reads it | Second execution cannot see it |

**A hanging grader is worse than a failing one.** That lesson is borrowed from
`learning_files`, where a C++ test whose loop condition depended on the function under
test hung forever against a safe no-op stub. Every limit above has a hard kill, not a
best-effort request to stop.

## Prompt injection

Corpus statements are researched from the open web and end up inside prompts. Candidate
code and transcripts also flow into grading prompts. Both are **untrusted input to the
model**.

Mitigations:

- **Structural, not lexical.** Untrusted content is placed in clearly delimited user-turn
  blocks; instructions live in the system prompt. We do not attempt to filter injection
  strings, because that is a losing game.
- **Corpus content is reviewed before merge.** A research run produces a diff a human
  reads. This is the main defence, and it is a strong one — the corpus is not
  attacker-controlled at runtime.
- **Capability limits on what injection can achieve.** The interviewer agent's tools are
  `run_code`, `check_answer`, `reveal_hint`, `record_observation`, `end_round`. There is
  no tool that writes to the corpus, sends anything outbound, or reads secrets. The worst
  outcome of a successful injection is a bad interview session, which is recoverable.

That last point matters more than the first two. **Design the tool surface so injection
is not worth much**, rather than trying to prevent every injection.

## Secrets

- Never in code, never in images, never in the repo. `.env` is gitignored; `.env.example`
  carries names and shapes only.
- In AWS: Secrets Manager, injected as environment variables at task start.
- IAM task roles are per-service and least-privilege. The API may invoke Bedrock and read
  one secret. The executor role can do neither.
- A secret scan runs before any push (`git grep` for key patterns); it caught nothing on
  the Phase 0 push, which is the baseline to maintain.

## The repo is public

Decided deliberately, overriding the default private-repo rule. Consequences to keep in
mind for the rest of the build:

- **Anything committed is permanent** — a rotated secret is still in history. Prevention
  is the only control that works.
- `.gitignore` already covers the dangerous defaults: `*.tfstate*` (which contains
  resource attributes and sometimes plaintext secrets), `*.tfvars`, `.terraform/`, `.env`,
  `*.pem`, `*.key`.
- **Phase 6 discipline:** account IDs, ARNs, VPC and subnet IDs go in `terraform.tfvars`
  (ignored) with a committed `.tfvars.example`. Terraform state goes in an S3 backend, not
  on disk.
- Enable GitHub secret scanning and push protection on the repo.

## Explicitly out of scope

Named so their absence is a decision rather than an oversight:

- **Multi-tenant isolation.** One user. The schema is multi-tenant-shaped; the code is not.
- **Hardened kernel isolation** (gVisor, Firecracker, microVMs). Fargate's isolation plus
  the six layers above is proportionate to running your own practice code. Revisit only if
  this ever serves other people.
- **DDoS protection** beyond what the ALB provides by default.
- **Supply-chain attestation** (SLSA, signed images). Dependencies are pinned via
  `uv.lock`; that is the proportionate control at this scale.
- **Audit logging for compliance.** `llm_calls` and `concept_evidence` are append-only for
  *correctness* reasons, not compliance ones.
