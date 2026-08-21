"""Graders. One module per modality, per docs/GRADING.md's four-grader split.

`coding` landed first because it needs no model: tests decide correctness, and a
measurement decides growth. `rubric` followed (system design and behavioral), then `quant`,
which is both — a deterministic answer check and the derivation judged against a rubric by
`rubric`'s own code rather than a second copy of it. All four modalities grade.

Every grader here is **pure and database-free**. It takes a corpus item and a submission
and returns a result plus the `concept_evidence` rows that result implies; writing them is
the session layer's job. That split is what lets a grader be re-run over an old artifact
to correct evidence — docs/ADAPTIVE.md's replay — instead of hand-patching mastery.
"""
