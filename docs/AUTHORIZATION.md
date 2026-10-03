# Authentication principal and RBAC

Phase 2 defines a framework-free `Principal` containing a validated Actor ID, Tenant ID, and one or
more explicit roles. Authentication adapters may be added later, but anonymous input never becomes
a principal: authorization entry points reject `None` before evaluating permissions.

The deterministic permission matrix is least-privilege and additive:

| Role | Permissions |
| --- | --- |
| Viewer | read incidents, evidence, and audit events |
| Operator | Viewer permissions; start/cancel investigation, request remediation, execute an already approved action |
| Approver | Viewer permissions; approve or reject eligible proposals |
| Admin | Viewer permissions; manage administrative configuration |

Admin does not implicitly approve or execute recovery. A person requiring multiple responsibilities
must receive multiple explicit roles, and downstream policy still enforces action risk and state.
Every resource authorization checks Tenant ID before permission. Medium/high-risk approval requires
an Approver in the same tenant whose Actor ID differs from the proposer; role union cannot bypass
that separation-of-duties check.

Tests exhaust the role map and prove rejection of anonymous, roleless, underprivileged, cross-tenant,
self-approval, wrong-role approval, and cross-tenant approval requests. These domain contracts are
the authority used by future API authentication adapters and endpoint dependencies.
