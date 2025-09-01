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
    # Normalized validity properties
    valid_content: str | None = Field(default=None, description="Content validity score from content evaluation")
    valid_formal: str | None = Field(default=None, description="Formal validity score from formal evaluation")  
    formalization: Formalization | None = None  # Formal logic representation
    

# Improvement Agent Schemas
class ExpectedConclusionImprovement(BaseModel):
    """Expected improvement in conclusion scores from a recommendation"""
    truth_score_improvement: str = Field(description="Expected improvement in truth score (0.0 to 1.0)")
    content_validity_improvement: str = Field(description="Expected improvement in content validity score (0.0 to 1.0)")
    formal_validity_improvement: str = Field(description="Expected improvement in formal validity score (0.0 to 1.0)")


class ImprovementProposition(BaseModel):
    """A proposition within an improvement recommendation"""
    symbol: str | None = Field(default=None, description="Symbol identifier for the proposition (e.g., 'B', 'C', 'D'). Leave blank for new propositions.")
    proposition: str = Field(description="The natural language proposition text")
    type: str = Field(description="Type of improvement", pattern="^(new|rewrite)$")
    original_symbol: str | None = Field(default=None, description="For rewrites, the symbol of the proposition being rewritten")
    original_proposition: str | None = Field(default=None, description="For rewrites, the original proposition text")
    placement: str = Field(description="Where to place this proposition", pattern="^(assumption|argument)$")
    justification_suggestions: list[str] = Field(description="Suggested justifications for this proposition")
    justifies_symbol: str | None = Field(default=None, description="For new propositions, the symbol of the existing proposition this new proposition justifies")


class ImprovementRecommendation(BaseModel):
    """A complete improvement recommendation set"""
    id: str = Field(description="Unique identifier for the recommendation")
    reasoning: str = Field(description="Why this improvement is suggested based on evaluation results")
    impact: str = Field(description="Expected impact level", pattern="^(high|medium|low)$")
    target_proposition: str = Field(description="Symbol of the proposition this recommendation supports")
    expected_conclusion_improvement: ExpectedConclusionImprovement = Field(description="Expected improvement in conclusion scores")
    propositions: list[ImprovementProposition] = Field(description="Array of propositions in this recommendation set")


class ImprovementSuggestions(BaseModel):
    """Complete improvement suggestions from the improvement agent"""
    recommendations: list[ImprovementRecommendation] = Field(description="Array of improvement recommendations")

