# research/ — running a corpus research session

This directory is the build-time half of the project. It produces
`packages/corpus/data/items/*.json` and nothing else; no service imports it at runtime.
The design is in [`docs/RESEARCH.md`](../docs/RESEARCH.md) — this file is the operator's
guide to actually running one.

## What runs where

| | Where | Why |
|---|---|---|
| Sweep, extract, cluster, rank, author | A Claude Code session on your machine | Needs web search, which Bedrock has no server-side tool for; and it is covered by the Max plan rather than the API bill |
| Validation and provenance checks | `make check`, and CI on every push | A corpus defect must fail a build, not a session |

## One run, start to finish

1. **Open a run record.** Copy an existing file in `runs/` to
   `runs/<YYYY-MM-DD>-<slug>.json` and fill in `run_id`, `started_at`, `domains`.
2. **Sweep.** Work the query families in `docs/RESEARCH.md` §1. Append *every* query to
   `queries` with its result count — including the ones that returned nothing. A dry
   sweep recorded is a dry sweep nobody repeats next quarter.
3. **Record what you saw.** Every URL the sweep surfaced goes in `sources_seen` with a
   `tier` and, when the page states one, a `published` date. Set `used: false` for now.
4. **Cluster and author.** Merge candidates that are the same question in different
   clothes into one archetype; write instances against the top-ranked ones. Flip
   `used: true` on each URL an item ends up citing.
5. **Close the run.** Set `ended_at` and `outcome`, then:

```sh
make corpus-validate   # schema, sources, originality, grading contracts
make research-check    # every cited URL traces to a recorded run, and back
make research-rank     # the density table — sanity-check the ordering
make test              # includes the reference-solution execution gate
make spot-check        # read 10 seeded-random instances before you believe any of it
```

## The two rules that are easy to break

**Write from the pattern, not from the page.** Read sources to learn *that* a pattern is
asked, then close them and write the problem yourself. The validator rejects any 12-word
run shared with a cited source and >15% 8-gram containment, but mechanical enforcement
only catches what reaches the file. Drafting with a source open produces near-copies that
either trip the check or slip through paraphrased, and the second outcome is worse.

**Don't pad a thin domain.** If a domain yields fewer archetypes than the others, that is
either real signal or a bad query family — record which in `notes` and revisit at the next
refresh. Inventing items to balance a table produces questions nobody is asked.

## Provenance, and why the check runs both ways

`make research-check` asserts that every URL an item cites appears in some run's
`sources_seen`, **and** that every entry marked `used` is really cited by an item. The
second direction is the one that gets skipped: without it a run record can claim credit
for sources nothing uses, and the provenance trail drifts from fiction into accepted fact.

## Layout

```
research/
├── runs/                  # one JSON per run — the `research_runs` provenance record
├── schema/run.schema.json # what a run record must contain
└── src/research/
    ├── runlog.py          # run-record schema + two-way provenance check
    ├── density.py         # evidence-density ranking (never model-judged novelty)
    └── spotcheck.py       # seeded sampling for the human gate
```
