"""nexus-agent — zero-config observability SDK for multi-agent AI systems.

Phase 1 scaffold: models are locked and importable. The public runtime API
(`init`, `trace`, `span`, `start_span`, `end_span`, `flush`) is implemented in
Phase 2.
"""

__version__ = "1.0.0"

from nexus_agent import models  # noqa: F401

__all__ = ["__version__", "models"]
