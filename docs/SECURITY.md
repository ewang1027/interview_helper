# Security

> **Status:** Isolation layer built and verified (2026-08-18); `POST /execute`, the test
> harness and the complexity probe built on top of it (2026-08-20), and `POST /probe`
> exposing that probe to the grader rather than only to CI (2026-08-20). **Authentication
> landed 2026-08-20** — see below; every `/api/v1` route now requires a session cookie.
> The six escape tests pass against real Docker, and **three of the six** were confirmed
> load-bearing by re-running them against a deliberately weakened sandbox — the PID,
> memory and contamination tests have had no negative control, and that is owed.
> Not built: `cpp`, `peak_rss_kb`. AWS-layer enforcement in **Phase 6**.
> "Measured behaviour" below records where this document's original claims were wrong.
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
and the process that holds the database password are never the same process.**

Two distinct claims live here and must not be run together. The **sandbox container** has
no DB client, no model client, no secrets and no outbound network — fully compromised, the
attacker has a box that can compute and nothing else. The **executor process** is weaker
than that: locally it holds the Docker socket in order to launch containers, which is
root-equivalent control of the host. That exposure is accepted, bounded, and explained in
[ARCHITECTURE](ARCHITECTURE.md#where-the-sandbox-actually-lives) — and under Fargate it
structurally cannot exist, because there is no socket to hold.

This is why `apps/executor/pyproject.toml` lists FastAPI, uvicorn, and Pydantic and
nothing else. Every dependency there is attack surface with no compensating benefit.

## Defence in depth for the executor

Six layers, each independently sufficient to prevent a class of harm:

| Layer | Control | Blocks |
|---|---|---|
| Network | No egress. Enforced by Docker network config locally and a security group with **no outbound rules** in AWS | Exfiltration, callbacks, dependency fetching |
| Filesystem | Read-only root, **plus a read-only `/etc` overlay and a non-root uid** — read-only root alone does not deny *reads*; one writable `tmpfs` scratch dir per execution, destroyed after | Persistence, cross-execution contamination |
| Identity | Runs as uid/gid `65534`, with `/etc` overlaid empty so there is no passwd entry to escalate through. **A shell is present and runnable** — measured: `/bin/sh -c 'id'` succeeds and returns uid 65534 — because `python:3.12-slim` is used as-is and only `/scratch` is `noexec`. Shelling out is possible and inherits the same uid, dropped capabilities and empty network namespace | Privilege escalation |
| Capabilities | All Linux capabilities dropped; `no-new-privileges` | Kernel-adjacent tricks |
| Syscalls | Docker's default seccomp profile. The "plus explicit deny" this row used to promise is **not** implemented — see "Measured behaviour" for why adding it as written would have *weakened* the sandbox | Sandbox escape primitives |
| Resources | Wall-clock timeout, memory cap, PID cap (64), CPU quota (0.5). **The first two are per-request overrides with a positive-integer floor and no ceiling** — a caller may ask for `wall_ms=3600000`; a server-side maximum is owed before the executor is reachable by anything but the API. `POST /probe` runs under the same limits but defaults them **higher** (60s wall, 512 MB) because it deliberately runs the submission at four sizes; its own internal budget stops the sweep at ~20s of process time, so the wall is a backstop rather than the real bound. That last claim was **false as first shipped** and CI caught it: the budget was only checked *between* sizes, so on a runner several times slower than the calibration machine a single size's first run blew through the wall mid-measurement. The driver now projects each size's cost from the growth already measured and refuses to start one it cannot afford (2026-08-21), which is what makes the budget the real bound on any machine | Denial of service against the host |
| Output | Captured stdout/stderr truncated at 64 KB | An unbounded stream filling the *caller's* memory — as effective a DoS as an allocation bomb inside the container. Note the grading consequence: if truncation eats the result marker, the run becomes a `harness_error`, so a very chatty correct solution fails |

Isolation is at the **infrastructure** layer, not in code. "The sandbox has no network" is
a security group with zero egress rules — not a Python check that can be bypassed by the
code it is checking.

## The six escape tests

Phase 2's gate. Each **must fail closed** — the attempt fails, the service survives, and
the failure is reported as a grading failure rather than a crash. They live in
`apps/executor/tests`, marked `sandbox`, and run in CI. A seventh `sandbox`-marked test,
`test_sanity_a_normal_program_runs`, is a control rather than an escape: without it, a
sandbox so broken it runs nothing would make all six pass.

| # | Test | Attempt | Required outcome |
|---|---|---|---|
| 1 | `test_no_network_egress` | DNS resolve and a raw TCP connect to a public address. Socket *creation* is deliberately not asserted — an `AF_INET` socket is still created successfully under `--network none`, so a test that only opens one proves nothing | Both fail; execution returns a normal failed result |
| 2 | `test_no_filesystem_escape` | Read `/etc/passwd`, read outside the scratch dir, write outside the scratch dir, traverse with `../` | Reads outside scratch denied; writes outside denied |
| 3 | `test_pid_exhaustion` | Fork bomb | Capped; the host survives. Asserted as `_docker_alive()` — the daemon still answers. `POST /execute` and its `/health` now exist, so this should be tightened to health-check the executor itself; it has not been, and that is open rather than blocked. Note the *result* can never say `pid_limit`: the container's own exit is not diagnostic (a recursive fork bomb was measured exiting **0** with empty output), so a capped run surfaces as `ok` or `harness_error` despite `pid_limit` being a declared outcome |
| 4 | `test_memory_bomb` | Allocate past the memory cap | OOM-killed; service survives; result reports the limit that was hit |
| 5 | `test_wall_clock_timeout` | Infinite loop | Killed at the timeout; result reports a timeout, not a hang |

Plus a sixth that is not an escape but is the one most likely to produce silently wrong
grades:

| 6 | `test_no_cross_execution_contamination` | Write a file, then run a second execution that reads it | Second execution cannot see it |

**A hanging grader is worse than a failing one.** That lesson is borrowed from
`learning_files`, where a C++ test whose loop condition depended on the function under
test hung forever against a safe no-op stub. Every limit above has a hard kill, not a
best-effort request to stop.

## Measured behaviour — where this document was wrong

Every control above was measured on Colima/macOS arm64 (Docker Engine 29.5.2, Ubuntu
24.04 kernel, cgroup v2) rather than taken from documentation. Most held exactly as
specified: `--network none`, `--pids-limit`, `--memory`, `--cap-drop=ALL`, and the tmpfs
scratch all did what this file claimed. Five things did not.

**1. `--read-only` does not deny reads.** It blocked every write, but `/etc/passwd` read
fine — so escape test 2 was unachievable as written. Denying reads needs a non-root
`--user` *plus* overlaying `/etc` with an empty read-only tmpfs. `/proc/1/environ` stays
readable regardless; there is no flag that closes it, so the compensating control is
that **the executor is injected with no environment secrets** — which the credential
rule above already required, now load-bearing for a second reason.

**2. A naive `subprocess(timeout=)` on `docker run` kills the CLI, not the container.**
The daemon keeps running the code, and because the client died `--rm` never fires, so
the container leaks too. Escape test 5 would have reported `timeout` perfectly correctly
while a runaway container burned CPU indefinitely — a green test verifying nothing. An
explicit `docker kill` is the actual enforcement (measured 0.10s). `docker stop` is not
an acceptable substitute: measured 10.1s against a process that ignores SIGTERM, which
is a hang wearing a timeout's clothes.

**3. A custom seccomp profile replaces the default rather than layering on it.** So the
natural reading of the Syscalls row — default profile *plus* a few denies — is not
expressible: a `defaultAction: SCMP_ACT_ALLOW` profile with deny rules would re-permit
everything Docker's default blocks, and the default was measured genuinely blocking
`unshare(CLONE_NEWUSER)`. Overriding it would have been a **net weakening dressed as
hardening**. Docker's default is therefore left in place unmodified.

The cost is a real, named gap: **`ptrace` is permitted under the default profile**
(measured: `PTRACE_TRACEME` returns 0). Closing it requires vendoring the ~900-line
default profile and appending denies, which is deferred rather than faked. The residual
risk is small — a single-process container, non-root, all capabilities dropped, with no
other process worth tracing — but it is a gap, not a solved problem. Custom profiles
*are* genuinely enforced under Colima (verified three ways, including `SCMP_ACT_KILL`
producing exit 159), so this is a scoping decision, not a platform limitation.

**4. Exit code 137 is ambiguous, so `--rm` cannot be used.** A wall-clock `docker kill`
and a kernel OOM kill both exit 137. Telling them apart needs
`docker inspect .State.OOMKilled`, which is impossible once `--rm` has destroyed the
container. Escape test 4 requires the result to report *which* limit was hit, so the
executor runs, inspects, then removes — with a labelled reaper for containers orphaned
between those steps.

**5. Neither the fork bomb nor the OOM kill can self-report.** At the PID cap the
process cannot fork enough to print, and a recursive fork bomb was measured **exiting 0
with empty output** because PID 1 backgrounded its children and returned. Two rules
follow: never infer success from exit 0 alone, and never expect the sandboxed process to
explain its own death — the evidence comes from outside the container.

One more trap, not a control failure but a portability one: **bind mounts silently
produce an empty directory on Colima** when the source is outside its shared mounts, with
no error at all. The same mount works natively on Linux CI. Candidate code is therefore
fed on **stdin**, never bind-mounted, which sidesteps a whole class of "green in CI,
silently mounts nothing locally".

### These tests were verified to fail

A passing escape test proves nothing on its own, so tests were re-run against a
deliberately weakened sandbox to confirm they are load-bearing: removing `--network none`
produced `tcp:REACHED`, removing the `/etc` overlay produced `READ_OK:/etc/passwd`, and
removing the explicit `docker kill` left the container **still running after its own
timeout**. All three would have failed the corresponding test. A
`test_sanity_a_normal_program_runs` control guards the opposite failure — a sandbox so
broken it runs nothing would otherwise make every escape test pass.

**Be precise about the coverage: that is three of the six.** Tests 3 (PID), 4 (memory) and
6 (cross-execution contamination) have never been run against a weakened sandbox, so their
load-bearingness is assumed rather than demonstrated. An earlier version of this banner
claimed "each was confirmed", which was the same overclaim this section exists to warn
about.

## Authentication

*Built 2026-08-20.* Until then every route was open, which was acceptable while the
surface was `/health` and `/execute` and stopped being acceptable the moment the session
layer started writing user data. What closed it:

| Control | What it does | Where it can fail |
|---|---|---|
| GitHub OAuth | The only way to obtain a session | GitHub's own account security is now part of this system's |
| `GITHUB_ALLOWED_ID` | One numeric account may log in; anyone else authenticates successfully and is refused `403` | Unset refuses everyone — deliberate, and the safe direction |
| HMAC-SHA256 cookie | `HttpOnly`, `Secure`, `SameSite=Lax`, 30-day expiry, signed with `SESSION_SECRET` | Anyone holding the secret can mint a session for any user id |
| Signed + echoed `state` | Login-CSRF: an attacker cannot complete their own login inside your browser | Ten-minute window, single use by cookie comparison |
| Query scoping | Session and mastery reads are filtered by the caller's user id | Not tenant isolation; one bad `where` clause is all it is |

**The threat this actually closes** is the deployed one. On a laptop, an open API behind no
port forward was a theoretical problem; in Phase 6 the same code sits behind a public ALB,
where "no auth" means the internet can start sessions, read every transcript, and spend
Bedrock credits. It was closed before that deploy rather than during it.

**What is deliberately not here:**

- **No rate limiting.** One user, and the expensive routes are behind the cookie. Login is
  the one unauthenticated write path, and it is bounded by GitHub's own throttling. Revisit
  when the ALB exists ([INFRA.md](INFRA.md)).
- **No server-side session store, so no instant revocation.** `POST /auth/logout` clears
  the browser's copy; a stolen cookie stays valid until it expires. Rotating
  `SESSION_SECRET` invalidates every session at once, and for one user that is the whole
  revocation story worth maintaining.
- **No CSRF token.** `SameSite=Lax` keeps a cross-site form from carrying the cookie into a
  state-changing `POST`. A same-site attacker would already be past everything else here.
- **`/openapi.json` and `/docs` stay open.** They describe the route surface, which is in a
  public repo anyway. Data is what the cookie guards.
- **No local-login route.** Development mints a cookie with `make login`, outside the
  process, from the same secret the server verifies with — so there is no code path in the
  deployed API that issues a session without GitHub. A dev bypass behind a flag would be
  one flag away from being a production bypass.

## Prompt injection

Corpus statements are researched from the open web and end up inside prompts. Candidate
code and transcripts also flow into grading prompts. Both are **untrusted input to the
model**.

Mitigations:

- **Structural, not lexical.** Untrusted content is placed in clearly delimited blocks and
  the surrounding instructions describe it as reference material — `api.agent.prompts` puts
  the corpus statement inside `<problem>…</problem>` under a paragraph saying that anything
  in it that reads like a direction is content, not an instruction. We do not attempt to
  filter injection strings, because that is a losing game.
- **Corpus content is reviewed before merge.** A research run produces a diff a human
  reads. This is the main defence, and it is a strong one — the corpus is not
  attacker-controlled at runtime.
- **Capability limits on what injection can achieve.** *Built 2026-08-20.* The interviewer
  agent's tools are `run_code`, `reveal_hint` and `end_round` — three, not the five this
  document listed, and the two absent ones are absent for reasons in
  [API.md](API.md#interviewer-agent-tools). There is no tool that writes to the corpus,
  sends anything outbound, or reads secrets. Two limits are worth naming because they close
  the obvious moves: `run_code` cannot choose its own tests (the corpus owns them, so a
  successful injection cannot make the sandbox run an arbitrary payload *and* mark it), and
  `reveal_hint` takes no item id (there is one item in play, so it cannot be used to read
  ahead). The worst outcome of a successful injection is a bad interview session, which is
  recoverable.

That last point matters more than the first two. **Design the tool surface so injection
is not worth much**, rather than trying to prevent every injection.

## Secrets

- Never in code, never in images, never in the repo. `.env` is gitignored; `.env.example`
  carries names and shapes only.
- **`SESSION_SECRET` and `GITHUB_CLIENT_SECRET` have no defaults**, in code or in
  `.env.example`. A fallback value in a public repo is a secret every clone already knows;
  the API answering `503` until one is set is the cheaper failure.
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
- **Result forgery by the candidate.** A graded run's result travels on the same stdout the
  candidate's code can write to. Taking the *last* `##LEARN-RESULT` marker and having the
  driver `os._exit(0)` closes the easy cases — a forged line printed early is superseded,
  and no `atexit` handler can print a later one — but a candidate who forges a marker and
  then exits the process itself leaves their line as the only one. Unclosable without a
  second channel, and out of scope: single user, no hostile population, and the only person
  deceived is the one practising.
