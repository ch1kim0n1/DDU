"""Discovery workers. Every one of them scans the operator, and only the operator.

There is a deliberate uniformity here: each worker's entry point takes a
``VerifiedIdentity`` as its first argument and calls ``assert_self`` before it
does anything else. No worker accepts a bare string target, so there is no
signature in this package that a free-text field could bind to.
"""

from .hibp import breach_findings
from .linkability import linkability_findings
from .sherlock import account_findings

__all__ = ["account_findings", "breach_findings", "linkability_findings"]
