# Historical scoring source binding

Frozen evaluation protocols record the implementation commit and source hashes used for their
original model calls. Later implementation changes must not make the old raw results impossible
to score. Historical FC4d scoring now verifies each runtime source against the exact Git blob at
the frozen implementation commit. Its separately approved scorer compatibility amendment still
binds the current scorer hash. New FC4d Provider execution explicitly requires current working
source hashes and therefore refuses source drift before a call. The archived protocol, model
outcomes, labels, thresholds and score remain unchanged.

The older FC4 development v3 publication test likewise checks source hashes at its frozen commit;
its current-code run preflight correctly refuses the later source revision. This separates
reproducibility of existing measurements from permission to create new outcomes under an old
protocol. Focused publication and preflight tests cover both paths.
