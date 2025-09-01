"""
Step schema for argument components.
This defines the data structure for individual steps in arguments and assumptions.
"""

from pydantic import BaseModel, Field
import warnings


class Formalization(BaseModel):
    """Formal logic representation of a proposition"""
    ascii: str
    json_structure: str | None = None
    endorsed: bool = False


class Step(BaseModel):
    """Steps in arguments or assumptions"""
    symbol: str
    proposition: str
    justifiers: list[str]
    truth: str
    valid: str = Field(default="", description="DEPRECATED: Use valid_content instead")  # Keep for backward compatibility
    # Normalized validity properties
    valid_content: str | None = Field(default=None, description="Content validity score from content evaluation")
    valid_formal: str | None = Field(default=None, description="Formal validity score from formal evaluation")  
    formalization: Formalization | None = None  # Formal logic representation
    
    def __init__(self, **data):
        super().__init__(**data)
        # Warn if using deprecated 'valid' property
        if data.get('valid') and data.get('valid') != "":
            warnings.warn(
                "The 'valid' property is deprecated. Use 'valid_content' for content validity scores.",
                DeprecationWarning,
                stacklevel=2
            )

