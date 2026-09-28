# Filtering overlapping actor boxes

English | [简体中文](actor-filter.zh-CN.md)

`state/actor_filter.py` filters likely duplicate vehicle observations before the actor ROI and nearest-K selection. It is enabled by `actor_overlap_filter: true`; set it to `false` for an unfiltered baseline. The filter uses current boxes and velocity estimated from past samples, with no future trajectory lookahead.

These are conservative geometry heuristics, not confirmed object identities:

- Candidate vehicle boxes must agree in heading within 15° and overlap by at least 50% of the smaller vertical extent. Pedestrians, cyclists, opposite headings and separated road levels are not merged.
- A large enclosing box is suppressed when it covers at least 80% of each of two smaller, mostly disjoint boxes. The large box must be at least 1.5 times each smaller box's area; the pair must jointly cover at least 55% of it. The two component observations are retained. This rule uses geometry even when estimated velocities disagree.
- Otherwise, similar-size boxes (area ratio at most 1.5) are treated as likely duplicates when overlap covers at least 80% of the smaller box and velocities differ by at most 3 m/s. Nearly coincident boxes with IoU at least 0.85 can also be suppressed despite missing/noisy velocity estimates; this exception is recorded in the evidence.
- The larger box is retained, with a stable ID tie-break. Suppression compares with retained representatives only; it does not merge transitive overlap chains. Partial or inconsistent overlaps remain in a review list.

Each decision logs the filter version, removed IDs, representative IDs and overlap evidence under `provenance.actor_filter`. Raw records are not mutated. The model receives the retained actor list; audit explanations are not added to its state. Filtering does not rewrite the simulator's replay actors or past driving decisions. Existing homepage rollout examples were recorded before this filter was enabled.

## Offline audit

```bash
PYTHONPATH=src python scripts/audit-actor-filter.py --run /absolute/path/to/run --render
```

Use the AlpaSim Python environment and the Noto Sans CJK font described in [setup](setup.md#labeled-rollout-previews). The command makes no model/API calls. It samples original scene actors at the saved decision timestamps and writes `actor-cleanup/`:

- `filtered-actors.jsonl`: original and retained world-coordinate observations, plus per-frame audit evidence.
- `summary.json`: affected frames, suppressed observation counts, unique IDs and overlaps retained for review.
- `before-after-en.gif`, `before-after-zh.gif`: matched before/after views following recorded GT, not a new rollout.

Counts cover all available source actors. `removed_ids_in_original_JEV_input` identifies suppressions that intersect the old logged input, while the preview count covers only visible targets. Neither proves a driving improvement; that requires a new rollout. A track ID can be retained in one frame and suppressed in another as evidence changes.
