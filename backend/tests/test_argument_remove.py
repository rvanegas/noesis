import pytest
import json
from unittest.mock import patch, MagicMock
from schemas.arguments import ArgumentsWithStep
from schemas.step import Step
from services.argument_service import ArgumentStepService
from services.agent_coordinator import coordinator


class TestArgumentRemove:
    """Test that argument.remove() behaves the same before and after changes"""
    
    def test_remove_step_from_argument_with_justifiers(self):
        """Test removing a step that has justifiers and is referenced by other steps"""
        # Create an argument with multiple steps and justifiers
        argument_data = {
            "assumptions": [],
            "argument": [
                Step(symbol="A", proposition="Socrates is a man", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="All men are mortal", justifiers=["A"], truth_score="1.0", valid="1.0"),
                Step(symbol="C", proposition="Socrates is mortal", justifiers=["B"], truth_score="1.0", valid="1.0")
            ],
            "loc": "argument",
            "index": 1,  # Remove step B (All men are mortal)
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
                # Create the argument object
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
    
        # Mock the coordinator to avoid actual agent queuing
        with patch.object(coordinator, 'queue_task') as mock_queue:
            # Call remove
            result = service.remove()
            
            # Verify the step was removed
            assert len(args.argument) == 2
            assert args.argument[0].symbol == "A"
            assert args.argument[1].symbol == "C"
            
            # Verify justifiers were properly transferred
            # Step C should now have justifiers ["A"] (B's justifiers) instead of ["B"]
            assert args.argument[1].justifiers == ["A"]
            
            # Verify the result structure (result is a JSON string)
            result_dict = json.loads(result)
            assert "argument" in result_dict
            assert len(result_dict["argument"]) == 2
            
            # Verify that argument state change was queued (builder, formalizer, content evaluator, and potentially form evaluator)
            assert mock_queue.call_count >= 3
            
            # Verify the calls were made with correct parameters
            calls = mock_queue.call_args_list
            agent_types = [call[1]['agent_type'] for call in calls]
            assert 'builder' in agent_types
            assert 'content_evaluator' in agent_types
            assert 'formalizer' in agent_types
    
    def test_remove_step_from_argument_without_justifiers(self):
        """Test removing a step that has no justifiers"""
        argument_data = {
            "assumptions": [],
            "argument": [
                Step(symbol="A", proposition="Socrates is a man", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="All men are mortal", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="C", proposition="Socrates is mortal", justifiers=["A"], truth_score="1.0", valid="1.0")
            ],
            "loc": "argument", 
            "index": 1,  # Remove step B (All men are mortal)
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
        
        with patch.object(coordinator, 'queue_task') as mock_queue:
            result = service.remove()
            
            # Verify the step was removed
            assert len(args.argument) == 2
            assert args.argument[0].symbol == "A"
            assert args.argument[1].symbol == "C"
            
            # Verify justifiers were not changed (B had no justifiers)
            assert args.argument[1].justifiers == ["A"]
            
            # Verify the result structure (result is a JSON string)
            result_dict = json.loads(result)
            assert "argument" in result_dict
            assert len(result_dict["argument"]) == 2
    
    def test_remove_step_from_assumptions(self):
        """Test removing a step from assumptions (should not transfer justifiers)"""
        argument_data = {
            "assumptions": [
                Step(symbol="A", proposition="Socrates is a man", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="All men are mortal", justifiers=["A"], truth_score="1.0", valid="1.0")
            ],
            "argument": [],
            "loc": "assumptions",
            "index": 1,  # Remove step B from assumptions
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
        
        with patch.object(coordinator, 'queue_task') as mock_queue:
            result = service.remove()
            
            # Verify the step was removed from assumptions
            assert len(args.assumptions) == 1
            assert args.assumptions[0].symbol == "A"
            
            # Verify the result structure (result is a JSON string)
            result_dict = json.loads(result)
            assert "assumptions" in result_dict
            assert len(result_dict["assumptions"]) == 1
    
    def test_remove_step_with_complex_justifier_transfer(self):
        """Test removing a step with complex justifier relationships"""
        argument_data = {
            "assumptions": [],
            "argument": [
                Step(symbol="A", proposition="Premise A", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="Premise B", justifiers=["A"], truth_score="1.0", valid="1.0"),
                Step(symbol="C", proposition="Premise C", justifiers=["A", "B"], truth_score="1.0", valid="1.0"),
                Step(symbol="D", proposition="Conclusion", justifiers=["C"], truth_score="1.0", valid="1.0")
            ],
            "loc": "argument",
            "index": 2,  # Remove step C (Premise C)
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
        
        with patch.object(coordinator, 'queue_task') as mock_queue:
            result = service.remove()
            
            # Verify the step was removed
            assert len(args.argument) == 3
            assert args.argument[0].symbol == "A"
            assert args.argument[1].symbol == "B"
            assert args.argument[2].symbol == "D"
            
            # Verify justifiers were properly transferred
            # Step D should now have justifiers ["A", "B"] (C's justifiers) instead of ["C"]
            assert set(args.argument[2].justifiers) == {"A", "B"}
            
            # Verify the result structure (result is a JSON string)
            result_dict = json.loads(result)
            assert "argument" in result_dict
            assert len(result_dict["argument"]) == 3
    
    def test_remove_step_queues_argument_state_change(self):
        """Test that remove() queues argument state change"""
        argument_data = {
            "assumptions": [],
            "argument": [
                Step(symbol="A", proposition="Step A", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="Step B", justifiers=["A"], truth_score="1.0", valid="1.0")
            ],
            "loc": "argument",
            "index": 1,
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
        
        with patch.object(coordinator, 'queue_task') as mock_queue:
            service.remove()
            
            # Verify that queue_task was called for multiple agents (builder, formalizer, content evaluator, and potentially form evaluator)
            assert mock_queue.call_count >= 3
            
            # Verify the calls were made with correct parameters
            calls = mock_queue.call_args_list
            agent_types = [call[1]['agent_type'] for call in calls]
            assert 'builder' in agent_types
            assert 'content_evaluator' in agent_types
            assert 'formalizer' in agent_types
            
            # Verify conversation_id was passed correctly in AgentInput objects
            for call in calls:
                agent_input = call[1]['agent_input']
                assert agent_input.conversation_id == 'test_session:1'
    
    def test_remove_step_preserves_other_arguments(self):
        """Test that remove() doesn't affect other arguments"""
        argument_data = {
            "assumptions": [],
            "argument": [
                Step(symbol="A", proposition="Step A", justifiers=[], truth_score="1.0", valid="1.0"),
                Step(symbol="B", proposition="Step B", justifiers=[], truth_score="1.0", valid="1.0")
            ],
            "loc": "argument",
            "index": 1,
            "conversation_id": "test_session:1",
            "snapshot_id": "test_snapshot_123"
        }
        
        args = ArgumentsWithStep(**argument_data)
        service = ArgumentStepService(args, "test_snapshot_123")
        
        # Store original argument
        original_argument = args.argument.copy()
        
        with patch.object(coordinator, 'queue_task'):
            result = service.remove()
            
            # Verify the step at index 1 was removed
            assert len(args.argument) == 1
            assert args.argument[0].symbol == "A"
            assert args.argument[0].proposition == "Step A"
            
            # Verify the removed step is no longer present
            step_b_symbols = [step.symbol for step in args.argument if step.symbol == "B"]
            assert len(step_b_symbols) == 0
