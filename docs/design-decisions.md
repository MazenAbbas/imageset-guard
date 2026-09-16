# v0.2 design decisions and sources

Concise record of the external evidence that materially shaped v0.2's
scope. Not a market survey -- only decisions with a source cited here.

## `class-only` layout (no split directories)

**Decision:** support `<class>/<image>` as an explicit second layout,
reported as one implicit `train` split, alongside the existing
`<split>/<class>/<image>` layout. No automatic detection between the two.

**Sources (accessed 2026-09-16):**
- [`torchvision.datasets.ImageFolder`](https://docs.pytorch.org/vision/stable/generated/torchvision.datasets.ImageFolder.html)
  documents `root/<class>/<image>` with **no split concept in the layout
  itself** -- a user creates separate `ImageFolder` instances per split
  directory. This is the class-only shape.
- [Hugging Face `datasets`: "Create an image dataset"](https://huggingface.co/docs/datasets/en/image_dataset)
  documents both `folder/<class>/<image>` (no splits; the guide explicitly
  warns that a single flat directory needs `drop_labels=False` if you want
  labels without inferring splits) and `folder/<split>/<class>/<image>`
  as two genuinely different, both-supported shapes.

**Conclusion:** both major ecosystems this tool's audience already uses
treat "no splits, just classes" as a first-class, common shape, not an
edge case -- worth implementing properly rather than deferring.

## Near-duplicate / perceptual-hash detection: deferred

**Decision:** not implemented in v0.2rc1. Evaluated against the release's
own stated conditions (opt-in, disabled by default, bounded memory/runtime,
strong tests against rotation/resize/recompression, no heavy CV/ML
dependency, no change to exact-duplicate guarantees).

**Reasoning:** meeting "strong tests showing known matches, non-matches,
and rotation/resize/compression behavior" with genuine confidence needs a
perceptual-hash algorithm choice (average hash, pHash, dHash, wavelet
hash), a validated similarity threshold, and adversarial test fixtures --
enough new surface area, on a tight release, to risk shipping a feature
whose false-positive/negative behavior isn't actually well understood yet.
Per this project's own decision rules ("prefer rejecting or deferring a
feature over shipping an unreliable version"), it is deferred to a future
release rather than shipped half-validated.

## Concurrency for scanning: deferred

**Decision:** v0.2 stays single-process, sequential.

**Reasoning:** the v0.1 benchmark evidence (see `CHANGELOG.md`) already
showed the single-process design comfortably meets the low-spec resource
target; the v0.2 benchmark (`benchmarks/README.md`) confirms this still
holds with the profile/policy work added. Multiprocessing/threading would
add real complexity to the identity-binding and TOCTOU protections between
inspection and hashing for an unproven throughput benefit on the stated
2-core/8GB baseline target, so it was not attempted this cycle.

## Property-based testing / fuzzing framework: not added

**Decision:** no new testing dependency (e.g. `hypothesis`) added this
cycle. Coverage of the same intent (path validation, policy parsing,
serialization round-trips, boundary values) is instead achieved with
deliberately chosen parametrized boundary-value tests, consistent with the
project's existing test style and its preference for the standard library
and existing dependencies.

## Mutation testing: manual review, not tooling

**Decision:** no mutation-testing framework (e.g. `mutmut`) was installed
this cycle. The highest-risk modules (path handling, policy validation,
duplicate relationships, exit-code selection, privacy sanitization) were
instead reviewed manually for the kind of defect mutation testing looks
for (boundary flips, condition inversions, off-by-one), and the resulting
gaps were closed with targeted tests rather than a scored run. This is a
narrower guarantee than a tool-measured mutation score and is reported as
such, not as an equivalent result.
