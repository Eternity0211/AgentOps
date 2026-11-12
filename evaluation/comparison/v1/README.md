# Paired comparison contract v1

`evaluation.paired_comparison` is the common create-only scorer for the final closure program. It
accepts only already paired baseline/candidate values. The caller must state how failed and aborted
runs were encoded; the scorer never drops them or loads Ground Truth.

For binary metrics it reports group rates, candidate-minus-baseline absolute and relative deltas,
a deterministic paired-bootstrap 95% interval, discordant counts, and the exact two-sided McNemar
test. For continuous metrics it reports the same fields for median and nearest-rank P95, with
paired-bootstrap intervals and an exact two-sided sign test. Holm adjustment is applied across all
declared metrics in one suite.

The beneficial direction is explicit. `IMPROVED` requires all of the following: the beneficial
interval excludes zero, the primary estimate meets the predeclared minimum relevant effect, the
Holm-adjusted p-value is below 0.05, and both the critical-safety and cost/latency gates pass.
An interval wholly in the harmful direction yields `REGRESSED`; every other result is
`NO_PROVEN_IMPROVEMENT`. Relative delta is `null` when the baseline is zero.

The CLI refuses to overwrite an existing result:

```text
python -m evaluation.paired_comparison --request <request.json> --output <new-result.json>
```

The bundled `example-request.json` is a contract fixture, not a measured product result.
