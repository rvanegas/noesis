"""
Usage example for Phase 1 Part 1: Input Normalization
Demonstrates how to use the enhanced Step model and normalized agent input schema.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from schemas.step import Step
from schemas.agent_input import AgentInput, AgentContext, TaskData, AgentMetadata, FilteredAgentInput


def example_enhanced_step_creation():
    """Example of creating enhanced Step objects with new attributes"""
    print("=== Enhanced Step Creation ===")
    
    # Create a step with all new attributes
    step = Step(
        symbol="A",
        proposition="Socrates is mortal",
        justifiers=[],
        truth_score="1.0",
        valid="1.0",  # Backward compatibility
        content_validity="0.9",  # New: content evaluation validity
        formal_validity="1.0",   # New: formal evaluation validity
        formalization="Mortal(Socrates)"  # New: formal logic representation
    )
    
    print(f"Step {step.symbol}: {step.proposition}")
    print(f"  Content validity: {step.content_validity}")
    print(f"  Formal validity: {step.formal_validity}")
    print(f"  Formalization: {step.formalization}")
    
    # Create a step with backward compatibility
    legacy_step = Step(
        symbol="B",
        proposition="All men are mortal",
        justifiers=["A"],
        truth_score="1.0",
        valid="1.0"
    )
    
    print(f"\nLegacy Step {legacy_step.symbol}: {legacy_step.proposition}")
    print(f"  New attributes default to None: {legacy_step.content_validity is None}")
    
    return step, legacy_step


def example_normalized_agent_input():
    """Example of creating normalized agent input"""
    print("\n=== Normalized Agent Input ===")
    
    # Create steps for the example
    assumption = Step(
        symbol="A",
        proposition="Socrates is a man",
        justifiers=[],
        truth_score="1.0",
        valid="1.0",
        formalization="Man(Socrates)"
    )
    
    argument_step = Step(
        symbol="B",
        proposition="Socrates is mortal",
        justifiers=["A"],
        truth_score="0.9",
        valid="0.95",
        content_validity="0.9",
        formal_validity="1.0",
        formalization="Mortal(Socrates)"
    )
    
    # Create context
    context = AgentContext(
        assumptions=[assumption],
        argument=[argument_step],
        file_ids=["philosophy_document.pdf"]
    )
    
    # Create task data
    task_data = TaskData(
        target_type="argument",
        target_content=None
    )
    
    # Create metadata
    metadata = AgentMetadata(
        triggered_by="user_action",
        trigger_source="proposition_added",
        ttl_seconds=3600
    )
    
    # Create normalized agent input
    agent_input = AgentInput(
        conversation_id="conv_123",
        snapshot_id="snap_456",
        context=context,
        task_data=task_data,
        metadata=metadata
    )
    
    print(f"Created agent input for conversation: {agent_input.conversation_id}")
    print(f"Snapshot: {agent_input.snapshot_id}")
    print(f"Assumptions: {len(agent_input.context.assumptions)}")
    print(f"Argument steps: {len(agent_input.context.argument)}")
    print(f"Files: {agent_input.context.file_ids}")
    
    return agent_input


def example_content_filtering():
    """Example of content filtering for different agent types"""
    print("\n=== Content Filtering ===")
    
    # Create agent input with mixed content
    step_with_formalization = Step(
        symbol="A",
        proposition="Socrates is mortal",
        justifiers=[],
        truth_score="1.0",
        valid="1.0",
        formalization="Mortal(Socrates)"
    )
    
    step_without_formalization = Step(
        symbol="B",
        proposition="All men are mortal",
        justifiers=["A"],
        truth_score="1.0",
        valid="1.0"
    )
    
    context = AgentContext(
        assumptions=[step_with_formalization, step_without_formalization],
        argument=[step_with_formalization],
        file_ids=[]
    )
    
    agent_input = AgentInput(
        conversation_id="conv_123",
        snapshot_id="snap_456",
        context=context,
        task_data=TaskData(target_type="argument"),
        metadata=AgentMetadata(triggered_by="user_action", trigger_source="test")
    )
    
    # Create filtered input for content evaluation (no formalization data)
    content_filtered = FilteredAgentInput.for_content_evaluation(agent_input)
    print("Content evaluation input:")
    print(f"  Assumptions: {len(content_filtered.context.assumptions)}")
    print(f"  Argument steps: {len(content_filtered.context.argument)}")
    print(f"  First assumption has formalization: {content_filtered.context.assumptions[0].formalization is not None}")
    
    # Create filtered input for formal evaluation (only formalized steps)
    formal_filtered = FilteredAgentInput.for_formal_evaluation(agent_input)
    print("\nFormal evaluation input:")
    print(f"  Assumptions: {len(formal_filtered.context.assumptions)}")
    print(f"  Argument steps: {len(formal_filtered.context.argument)}")
    print(f"  Only includes formalized steps: {len(formal_filtered.context.assumptions) == 1}")
    






def main():
    """Run all examples"""
    print("Phase 1 Part 1: Input Normalization Examples")
    print("=" * 50)
    
    # Run examples
    example_enhanced_step_creation()
    agent_input = example_normalized_agent_input()
    example_content_filtering()
    
    print("\n" + "=" * 50)
    print("All examples completed successfully!")
    
    return agent_input


if __name__ == "__main__":
    main()
