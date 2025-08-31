# Improvement Agent Design and Implementation Plan

## Overview

This document outlines the design and implementation plan for reworking the current "Argument Builder" agent into an "Improvement Agent" that provides intelligent recommendations for argument enhancement based on evaluation results.

## Current State Analysis

### Existing Argument Builder
- **Trigger**: Runs immediately after every argument change
- **Function**: Generates justifications for user-added propositions
- **Scope**: Limited to suggesting justifications for existing propositions
- **Timing**: Reactive to argument state changes, not evaluation results

### Problems with Current Approach
1. **Premature execution** - Runs before content/formal evaluation is complete
2. **Limited scope** - Only suggests justifications, not improvements
3. **No evaluation context** - Doesn't consider truth/validity scores
4. **Inefficient** - Runs on every change regardless of evaluation state
5. **Missed opportunities** - Doesn't suggest new propositions or rewrites

## Proposed Improvement Agent Design

### Core Concept
Transform the argument builder into an intelligent improvement agent that:
- **Analyzes evaluation results** to identify weaknesses in the argument structure
- **Creates cohesive recommendation sets** that work together to strengthen the concluding proposition
- **Suggests new supporting propositions** that provide evidence or reasoning to support the conclusion
- **Proposes refinements** of existing propositions to improve clarity, logic, or precision
- **Ensures coherence** - each recommendation is a complete, self-contained improvement set
- **Targets conclusion improvement** - all recommendations ultimately aim to improve the concluding proposition's scores
- **Runs at the right time** - after evaluation results are available

### Agent Behavior

#### Trigger Conditions
1. **Content Evaluation Trigger**: When content evaluation results are available AND not all propositions have endorsed formalizations
2. **Formal Evaluation Trigger**: When formal evaluation results are available AND all propositions have endorsed formalizations

#### Improvement Types
Each recommendation is a cohesive set of propositions that work together to strengthen the concluding proposition (the thesis/conclusion):

1. **Conclusion-Supporting Premises**: New propositions that provide evidence or reasoning to directly support the concluding proposition
2. **Premise Strengthening**: New propositions that support existing premises, thereby strengthening the overall argument for the conclusion
3. **Proposition Refinements**: Rewrites of existing propositions to improve clarity, logic, or precision, making the argument more compelling
4. **Mixed Recommendations**: Combinations of new supporting propositions and refined existing propositions that together strengthen the conclusion
5. **Justification Sets**: Multiple propositions that together provide comprehensive justification for the concluding proposition

Each recommendation must demonstrate how it contributes to improving the concluding proposition's truth, content validity, and formal validity scores.

### Input Context
The improvement agent will receive:
- **Current argument state** (assumptions + argument steps)
- **Content evaluation results** (truth/validity scores with reasoning)
- **Formal evaluation results** (formal validity scores with reasoning)
- **Formalization status** (which propositions have endorsed formalizations)
- **Previous improvement suggestions** (to avoid repetition)
- **Concluding proposition identification** (the first entered proposition, last in steps list)
- **Current conclusion scores** (truth, content validity, formal validity of the concluding proposition)

### Output Structure
```typescript
interface ImprovementSuggestions {
  recommendations: {
    id: string
    reasoning: string
    confidence: number
    impact: 'high' | 'medium' | 'low'
    target_proposition: string  // Symbol of proposition this recommendation supports
    expected_conclusion_improvement: {
      truth_score_improvement: number
      content_validity_improvement: number
      formal_validity_improvement: number
      reasoning: string  // How this recommendation will improve conclusion scores
    }
    propositions: {
      symbol: string
      proposition: string
      type: 'new' | 'rewrite'
      original_symbol?: string  // For rewrites, the symbol being rewritten
      original_proposition?: string  // For rewrites, the original proposition
      placement: 'assumption' | 'argument'
      justification_suggestions: string[]
    }[]
  }[]
}
```

## Implementation Plan

### Phase 1: Agent Prompt and Schema Design

#### 1.1 System Prompt Design
- **Role definition**: Improvement agent that analyzes evaluation results
- **Input format**: Structured input with argument state and evaluation results
- **Output format**: JSON schema for improvement suggestions
- **Reasoning requirements**: Explain why each improvement is suggested
- **Confidence scoring**: Rate confidence in each suggestion

#### 1.2 Output Schema Definition
- Define comprehensive JSON schema for improvement suggestions
- Include validation rules for each suggestion type
- Ensure schema supports all improvement categories

#### 1.3 Example Generation
- Create examples of cohesive recommendation sets that improve conclusion scores
- Include examples of different evaluation scenarios (low conclusion truth scores, low validity scores, etc.)
- Demonstrate how multiple propositions work together to strengthen the concluding proposition
- Show examples of mixed recommendations (new + rewritten propositions) that improve conclusion scores
- Demonstrate proper reasoning and confidence scoring for complete recommendation sets
- Include examples of expected conclusion score improvements with detailed reasoning

### Phase 2: Backend Implementation

#### 2.1 Agent Class Creation
- Create `ImprovementAgent` class extending base agent
- Implement `generate_improvements()` method
- Add proper input/output handling
- Ensure complete independence from existing agents

#### 2.2 New Trigger Logic Implementation
- Create new trigger functions independent of existing agent triggers
- Implement `queue_improvement_agent_if_ready()` function
- Add trigger logic in evaluation completion handlers
- Ensure no modification to existing trigger mechanisms

#### 2.3 Integration with Evaluation Results
- Create new agent input creation methods for improvement agent
- Ensure proper data flow from content/formal evaluators
- Handle cases where evaluation results are incomplete
- Maintain separation from existing agent input creation

### Phase 3: Frontend Integration

#### 3.1 New UI Component Creation
- Create new `ImprovementRecommendations.tsx` component for displaying recommendation sets
- Create new component for displaying cohesive recommendation sets
- Add user interaction for accepting/rejecting entire recommendation sets
- Show which existing proposition each recommendation supports
- Display the relationship between propositions within each recommendation set
- Show expected conclusion score improvements for each recommendation
- Highlight the concluding proposition and its current scores
- Ensure no modification to existing `AllAgentResults.tsx` during development

#### 3.2 New State Management
- Add new improvement recommendation sets to conversation store
- Implement new recommendation set acceptance/rejection logic
- Create new snapshot management for improvement state
- Track which recommendation sets have been applied to which propositions
- Ensure new state management doesn't interfere with existing agent result state

#### 3.3 User Interface Design
- Design clear presentation of improvement recommendation sets
- Add visual indicators for recommendation types (new propositions, rewrites, mixed)
- Show the target proposition each recommendation supports
- Implement user feedback mechanisms for entire recommendation sets
- Display the logical flow within each recommendation set
- Show current vs. expected conclusion scores for each recommendation
- Provide clear visualization of how each recommendation strengthens the conclusion

### Phase 4: New Trigger Logic Implementation

#### 4.1 Content Evaluation Trigger
```python
def should_queue_improvement_agent_content(conversation_id: str, snapshot_id: str) -> bool:
    # Check if content evaluation results are available
    # Check if not all propositions have endorsed formalizations
    # Check if improvement agent hasn't run recently
    # Ensure this doesn't interfere with existing agent triggers
    pass
```

#### 4.2 Formal Evaluation Trigger
```python
def should_queue_improvement_agent_formal(conversation_id: str, snapshot_id: str) -> bool:
    # Check if formal evaluation results are available
    # Check if all propositions have endorsed formalizations
    # Check if improvement agent hasn't run recently
    # Ensure this doesn't interfere with existing agent triggers
    pass
```

#### 4.3 New Integration Points
- Create new `queue_improvement_agent_if_ready()` function
- Add improvement agent queuing after content evaluation completion
- Add improvement agent queuing after formal evaluation completion
- Implement proper sequencing and dependency management
- Ensure no modification to existing agent trigger mechanisms

## Technical Considerations

### Data Dependencies
- **Content evaluation results** must be available for content-triggered improvements
- **Formal evaluation results** must be available for formal-triggered improvements
- **Formalization status** must be tracked for trigger logic

### Performance Considerations
- **Conditional execution** prevents unnecessary agent runs
- **Result caching** avoids re-running on same evaluation state
- **Incremental improvements** build on previous suggestions
- **Independent execution** - new agent doesn't interfere with existing agent performance

### User Experience
- **Clear timing** - users understand when improvement recommendations are generated
- **Contextual recommendations** - improvement sets relate to specific evaluation issues and target propositions
- **Cohesive presentation** - each recommendation set is presented as a complete, coherent improvement
- **Actionable feedback** - users can easily accept/reject entire recommendation sets
- **Logical flow** - users understand how the propositions within each recommendation work together

## Implementation Strategy

### Clean Implementation Approach
This implementation will introduce a new agent type (`improvement_agent`) and ultimately retire the existing `builder` and `rewriter` agent types. There will be no incremental code replacement - the new agent will be built as a complete, independent system.

### Phase 1: New Agent Development
- Implement `ImprovementAgent` as a completely new agent type
- Create new agent prompts, schemas, and processing logic
- Implement new trigger mechanisms independent of existing agents
- Test the new agent in isolation with manual triggering

### Phase 2: Integration and Testing
- Integrate the new agent into the existing agent coordination system
- Test trigger logic and data flow with the new agent
- Verify that the new agent works alongside existing agents
- Ensure no interference with current agent functionality

### Phase 3: Frontend Integration
- Create new UI components for improvement recommendations
- Implement new state management for improvement suggestions
- Test end-to-end workflow with the new agent
- Ensure seamless integration with existing UI

### Phase 4: Agent Retirement
- Once the improvement agent is stable and tested, remove `builder` and `rewriter` agents
- Clean up old agent references, triggers, and UI components
- Update documentation and examples to reflect the new system
- Ensure no breaking changes to existing functionality during transition

## Success Metrics

### Functional Metrics
- **Conclusion score improvement** - recommendations actually improve the concluding proposition's truth, content validity, and formal validity scores
- **Recommendation quality** - recommendation sets are coherent, relevant, and actionable
- **Trigger accuracy** - agent runs at appropriate times
- **User acceptance** - high rate of recommendation set acceptance
- **Coherence score** - propositions within each recommendation work together effectively
- **Prediction accuracy** - expected conclusion improvements match actual improvements

### Performance Metrics
- **Reduced unnecessary runs** - fewer agent executions
- **Faster response times** - improvements generated when needed
- **Better resource utilization** - agents run only when valuable

### User Experience Metrics
- **Clearer timing** - users understand when improvement recommendations appear
- **Better recommendation sets** - more coherent and helpful recommendation sets
- **Improved conclusion scores** - measurable improvement in concluding proposition's truth, validity, and formal validity scores
- **Logical coherence** - users can follow the logical flow within each recommendation set
- **Clear improvement visualization** - users can see how recommendations will improve conclusion scores

## Risk Mitigation

### Technical Risks
- **Complex trigger logic** - implement comprehensive testing
- **Data dependency issues** - ensure proper sequencing
- **Performance impact** - monitor agent execution times
- **Integration conflicts** - ensure new agent doesn't interfere with existing agents
- **Breaking changes** - maintain backward compatibility during development

### User Experience Risks
- **Confusing timing** - provide clear feedback about when improvement recommendations are generated
- **Poor recommendation sets** - implement quality filtering and user feedback
- **Overwhelming UI** - design clear presentation of recommendation sets
- **Incoherent recommendations** - ensure propositions within each recommendation work together logically

## Next Steps

1. **Review and refine design** - gather feedback on approach
2. **Implement Phase 1** - create agent prompt and schema for new agent type
3. **Build backend foundation** - implement new agent class and basic logic
4. **Test new trigger mechanisms** - verify proper timing and dependencies
5. **Create new frontend components** - build new UI for improvement recommendations
6. **Test integration** - ensure new agent works alongside existing agents
7. **Plan agent retirement** - prepare for removal of builder and rewriter agents
8. **Iterate and improve** - refine based on user feedback and testing

This design transforms the argument builder from a simple justification generator into an intelligent improvement agent that provides contextual, evaluation-driven recommendation sets for argument enhancement. Each recommendation is a cohesive set of propositions that work together to strengthen the concluding proposition, with the ultimate goal of improving its truth, content validity, and formal validity scores. The success of recommendations is measured by their ability to enhance the concluding proposition's evaluation scores, ensuring that improvements are coherent, complete, and demonstrably effective.
