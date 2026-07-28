"""DDU Mirror — intelligence, discovery, and agent layer (Engineer B).

The defensive carve-out of the DDU engine: same lifecycle, inverted subject.
Nothing in this package can be pointed at a person who has not proven control
of the identity being scanned.

Entry points other engineers use:

* ``schema`` — the locked findings contract (A, C, D all consume it)
* ``mock.generate`` — schema-valid fake findings (C, D)
* ``api.router`` — the HTTP surface (A mounts it at ``/intel``)
* ``redaction`` — the outbound boundary (D routes voice through it)
* ``orchestrator`` — propose / approve / edit / reject (D drives it)
"""

from .schema import CONTRACT_VERSION

__version__ = "0.1.0"
__all__ = ["CONTRACT_VERSION", "__version__"]
