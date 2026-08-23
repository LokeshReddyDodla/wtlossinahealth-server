"""Public import path: ``from aihealth_brain import assess``.

Implementation lives in ``lib/ai_foundation/clinical/aihealth_brain.py``.
Drop the 145KB v2.2.0 pin as ``aihealth_brain_pin.py`` — do not replace
this shim, or the SAFETY lever-strip / fail-closed wrappers are lost
unless the meal-agent shadow runner is still in place.
"""

from lib.ai_foundation.clinical.aihealth_brain import (
    __version__,
    assess,
    sanitize_assess_result,
)

__all__ = ["assess", "sanitize_assess_result", "__version__"]
