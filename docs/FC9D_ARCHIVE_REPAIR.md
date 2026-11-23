# FC9d historical archive byte repair

The Git-object auditor found 891 hash mismatches across four older evaluation archives. Every
corresponding local raw file still matched its frozen SHA-256 manifest before repair:

| Archive | Mismatched Git blobs | Local raw files matching manifest |
| --- | ---: | ---: |
| Structured reliability v1 | 356 | 356 |
| Structured reliability v3 | 351 | 351 |
| Diagnosis quality v1 | 182 | 182 |
| Diagnosis generalization v1 | 2 | 2 |
| Total | 891 | 891 |

The staged repair changes only line endings in those 891 files: a Git diff that ignores end-of-line
whitespace has no remaining difference. Exact path attributes now retain original archive bytes.
No manifest, frozen protocol, scored outcome, result value or evaluation label was changed or
rescored. The precommit Git tree audit verifies all 37 manifests and 34,134 archived files with
zero problems; the committed revision must pass the same audit.
