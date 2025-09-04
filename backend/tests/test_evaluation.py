import pytest
import json
from unittest.mock import patch
from services.agents import ContentEvaluationAgent
from services.agent_coordinator import coordinator
from schemas.agent_input import FilteredAgentInput, AgentData
from schemas.step import Step


class TestEvaluationAgent:
    """Test the evaluation agent functionality"""
    
    def test_content_mode_evaluation(self):
        """Test that evaluation works correctly in content mode"""
        agent = ContentEvaluationAgent(coordinator)
        
        # Mock the coordinator to return no formalizations (content mode)
        mock_existing_results = []
        
        # Mock the GPT response for content mode
        mock_response = {
            "proposition_evaluations": [
                {"proposition": "Socrates is a man", "truth_value": 0.9, "reasoning": "Historical fact"},
                {"proposition": "All men are mortal", "truth_value": 0.95, "reasoning": "Universal biological truth"},
                {"proposition": "Socrates is mortal", "truth_value": 0.9, "reasoning": "Valid conclusion from premises"}
            ],
            "overall_truth_score": 0.95,
            "truth_issues": [],
            "recommendations": ["Argument is logically sound and well-structured"]
        }
        
        with patch('services.agents.agent_gpt_evaluate_content') as mock_gpt, \
             patch.object(coordinator, 'get_conversation_results', return_value=mock_existing_results):
            
            mock_gpt.call.return_value = json.dumps(mock_response)
            
            # Test data - create proper FilteredAgentInput
            agent_input = FilteredAgentInput(
                conversation_id='test_conversation',
                snapshot_id='test_snapshot',
                agent_data=AgentData(
                    assumptions=[],
                    argument=[
                        Step(symbol='A', proposition='Socrates is a man', justifiers=[], truth_score='0.9', content_validity='0.9', formal_validity='0.9'),
                        Step(symbol='B', proposition='All men are mortal', justifiers=[], truth_score='0.95', content_validity='0.95', formal_validity='0.95'),
                        Step(symbol='C', proposition='Socrates is mortal', justifiers=[], truth_score='0.9', content_validity='0.9', formal_validity='0.9')
                    ],
                    latest_results=[],
                    target_type='argument',
                    target_content=None
                ),
                file_ids=[]
            )
            
            # Call the evaluation agent
            result = agent.evaluate_propositions(agent_input)
            
            # Verify the result is in content mode
            assert result.agent_type == "content_evaluator"
            assert result.operation == "evaluate_propositions"
            # Note: evaluation_mode is no longer included in the result data
    
    def test_content_evaluator_always_evaluates_content(self):
        """Test that content evaluator always evaluates content, regardless of formalizations"""
        agent = ContentEvaluationAgent(coordinator)
        
        # Mock the coordinator to return formalizations (but content evaluator ignores them)
        mock_existing_results = [
            {
                'agent_type': 'formalizer',
                'data': {
                    'proposition': 'Socrates is a man',
                    'ascii': 'P(a)',
                    'reasoning': 'Direct predicate application'
                }
            }
        ]
        
        # Mock the GPT response for content evaluation
        mock_response = {
            "proposition_evaluations": [
                {"proposition": "Socrates is a man", "truth_value": 0.9, "reasoning": "Historical fact"}
            ],
            "overall_truth_score": 0.9,
            "truth_issues": [],
            "recommendations": ["Argument is sound"]
        }
        
        with patch('services.agents.agent_gpt_evaluate_content') as mock_gpt, \
             patch.object(coordinator, 'get_conversation_results', return_value=mock_existing_results):
            
            mock_gpt.call.return_value = json.dumps(mock_response)
            
            # Test data - create proper FilteredAgentInput
            agent_input = FilteredAgentInput(
                conversation_id='test_conversation',
                snapshot_id='test_snapshot',
                agent_data=AgentData(
                    assumptions=[],
                    argument=[
                        Step(symbol='A', proposition='Socrates is a man', justifiers=[], truth_score='0.9', content_validity='0.9', formal_validity='0.9')
                    ],
                    latest_results=[],
                    target_type='argument',
                    target_content=None
                ),
                file_ids=[]
            )
            
            # Call the evaluation agent
            result = agent.evaluate_propositions(agent_input)
            
            # Verify the result is always in content mode
            assert result.agent_type == "content_evaluator"
            assert result.operation == "evaluate_propositions"
            # Note: evaluation_mode is no longer included in the result data
    
    def test_content_evaluator_ignores_formalizations(self):
        """Test that content evaluator ignores formalizations and always evaluates content"""
        agent = ContentEvaluationAgent(coordinator)
        
        # Test with formalizations present (content evaluator should ignore them)
        mock_with_formalizations = [
            {
                'agent_type': 'formalizer',
                'data': {
                    'proposition': 'Socrates is a man',
                    'ascii': 'P(a)',
                    'reasoning': 'Direct predicate application'
                }
            }
        ]
        
        with patch.object(coordinator, 'get_conversation_results', return_value=mock_with_formalizations):
            
            # Test data - create proper FilteredAgentInput
            agent_input = FilteredAgentInput(
                conversation_id='test_conversation',
                snapshot_id='test_snapshot',
                agent_data=AgentData(
                    assumptions=[],
                    argument=[
                        Step(symbol='A', proposition='Socrates is a man', justifiers=[], truth_score='0.9', content_validity='0.9', formal_validity='0.9')
                    ],
                    latest_results=[],
                    target_type='argument',
                    target_content=None
                ),
                file_ids=[]
            )
            
            # The content evaluator should always evaluate content, regardless of formalizations
            result = agent.evaluate_propositions(agent_input)
            assert result.agent_type == "content_evaluator"
            # Note: evaluation_mode is no longer included in the result data


if __name__ == "__main__":
    pytest.main([__file__]) 