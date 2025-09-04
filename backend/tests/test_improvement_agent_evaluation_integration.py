"""Test the improvement agent's integration with evaluation results"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from services.agent_coordinator import AgentCoordinator
from services.agents import ImprovementAgent
from schemas.agent_input import AgentInput, AgentData
from schemas.step import Step
from schemas.arguments import ArgumentData


class TestImprovementAgentEvaluationIntegration:
    """Test that the improvement agent properly integrates with evaluation results"""

    def setup_method(self):
        """Set up test fixtures"""
        self.coordinator = AgentCoordinator()
        
        # Create test step
        self.test_step = Step(
            symbol="A",
            proposition="Test proposition",
            justifiers=[],
            truth_score="0.5",
            content_validity="0.4",
            formal_validity="0.3"
        )
        
        # Create test argument data
        self.argument_data = ArgumentData(
            argument=[self.test_step],
            assumptions=[],
            file_ids=[]
        )

    def test_create_improvement_agent_input_includes_evaluation_results(self):
        """Test that create_improvement_agent_input includes evaluation results"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Mock conversation results to include evaluation data
        mock_results = [
            Mock(
                agent_type='content_evaluator',
                operation='evaluate_propositions',
                result_content={'truth_evaluations': [{'symbol': 'A', 'truth_value': '0.5'}]},
                confidence=0.8,
                reasoning='Test evaluation',
                snapshot_id=snapshot_id,
                processed_at=1234567890.0,
                model_dump=Mock(return_value={
                    'agent_type': 'content_evaluator',
                    'operation': 'evaluate_propositions',
                    'result_content': {'truth_evaluations': [{'symbol': 'A', 'truth_value': '0.5'}]},
                    'confidence': 0.8,
                    'reasoning': 'Test evaluation',
                    'snapshot_id': snapshot_id,
                    'processed_at': 1234567890.0
                })
            ),
            Mock(
                agent_type='form_evaluator',
                operation='evaluate_propositions',
                result_content={'validity_evaluations': [{'symbol': 'A', 'validity_value': '0.6'}]},
                confidence=0.7,
                reasoning='Test formal evaluation',
                snapshot_id=snapshot_id,
                processed_at=1234567890.0,
                model_dump=Mock(return_value={
                    'agent_type': 'form_evaluator',
                    'operation': 'evaluate_propositions',
                    'result_content': {'validity_evaluations': [{'symbol': 'A', 'validity_value': '0.6'}]},
                    'confidence': 0.7,
                    'reasoning': 'Test formal evaluation',
                    'snapshot_id': snapshot_id,
                    'processed_at': 1234567890.0
                })
            )
        ]
        
        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            agent_input = self.coordinator.create_improvement_agent_input(
                conversation_id, snapshot_id, self.argument_data
            )
            
            # Verify evaluation results are included in latest_results
            assert len(agent_input.agent_data.latest_results) == 2  # content + formal evaluation
            assert any(r['agent_type'] == 'content_evaluator' for r in agent_input.agent_data.latest_results)
            assert any(r['agent_type'] == 'form_evaluator' for r in agent_input.agent_data.latest_results)
            
            # Verify that latest_results is also populated with evaluation data (following existing pattern)
            assert len(agent_input.agent_data.latest_results) == 2  # content + formal evaluation
            assert any(r['agent_type'] == 'content_evaluator' for r in agent_input.agent_data.latest_results)
            assert any(r['agent_type'] == 'form_evaluator' for r in agent_input.agent_data.latest_results)
            
            # Verify content evaluations
            content_evaluations = [r for r in agent_input.agent_data.latest_results if r['agent_type'] == 'content_evaluator']
            assert len(content_evaluations) == 1
            assert content_evaluations[0]['agent_type'] == 'content_evaluator'
            assert content_evaluations[0]['result_content']['truth_evaluations'][0]['symbol'] == 'A'
            
            # Verify formal evaluations
            formal_evaluations = [r for r in agent_input.agent_data.latest_results if r['agent_type'] == 'form_evaluator']
            assert len(formal_evaluations) == 1
            assert formal_evaluations[0]['agent_type'] == 'form_evaluator'
            assert formal_evaluations[0]['result_content']['validity_evaluations'][0]['symbol'] == 'A'
            
            # Verify conclusion information
            assert agent_input.agent_data.argument[-1].proposition == "Test proposition"
            assert agent_input.agent_data.argument[-1].truth_score == "0.5"
            assert agent_input.agent_data.argument[-1].content_validity == "0.4"
            assert agent_input.agent_data.argument[-1].formal_validity == "0.3"

    def test_create_improvement_agent_input_handles_missing_evaluation_results(self):
        """Test that create_improvement_agent_input handles missing evaluation results gracefully"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Mock conversation results with no evaluation data
        mock_results = [
            Mock(
                agent_type='builder',
                operation='build_argument',
                result_content={'propositions': []},
                confidence=0.8,
                reasoning='Test builder',
                snapshot_id=snapshot_id,
                processed_at=1234567890.0
            )
        ]
        
        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            agent_input = self.coordinator.create_improvement_agent_input(
                conversation_id, snapshot_id, self.argument_data
            )
            
            # Verify evaluation results are empty
            assert len(agent_input.agent_data.latest_results) == 0

    def test_improvement_agent_requires_evaluation_results(self):
        """Test that improvement agent requires evaluation results to function"""
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create agent input without evaluation results
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[self.test_step],
                assumptions=[],
                target_type="argument",
                target_content=None,
                latest_results=[]  # No evaluation results
            ),
            file_ids=[]
        )
        
        # The agent should handle missing evaluation results gracefully and return an error result
        result = agent.generate_improvements(agent_input)
        
        # Verify the agent returned an error result instead of crashing
        assert result.confidence == 0.0
        assert "error" in result.result_content
        assert "Improvement agent requires at least content or formal evaluation results" in result.result_content["error"]

    def test_improvement_agent_requires_sufficient_evaluation_data(self):
        """Test that improvement agent requires sufficient evaluation data"""
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create agent input with empty evaluation results
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[self.test_step],
                assumptions=[],
                target_type="argument",
                target_content=None,
                latest_results=[]  # Empty evaluation results
            ),
            file_ids=[]
        )
        
        # The agent should handle insufficient evaluation data gracefully and return an error result
        result = agent.generate_improvements(agent_input)
        
        # Verify the agent returned an error result instead of crashing
        assert result.confidence == 0.0
        assert "error" in result.result_content
        assert "Improvement agent requires at least content or formal evaluation results" in result.result_content["error"]

    @patch('services.agent_prompts.agent_gpt_improvement.call')
    def test_improvement_agent_processes_evaluation_results_successfully(self, mock_gpt_call):
        """Test that improvement agent successfully processes evaluation results"""
        # Mock the GPT response
        mock_gpt_call.return_value = '{"recommendations": [{"id": "rec_001", "reasoning": "Test reasoning", "impact": "high", "target_proposition": "A", "expected_conclusion_improvement": {"truth_score_improvement": "+0.3", "content_validity_improvement": "+0.2", "formal_validity_improvement": "+0.1"}, "propositions": [{"symbol": null, "proposition": "Test proposition", "type": "new", "placement": "argument", "justifies_symbol": "A", "justification_suggestions": ["Test justification"]}]}]}'
        
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create agent input with evaluation results
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[self.test_step],
                assumptions=[],
                target_type="argument",
                target_content=None,
                latest_results=[
                    {
                        'agent_type': 'content_evaluator',
                        'operation': 'evaluate_propositions',
                        'result_content': {'truth_evaluations': [{'symbol': 'A', 'truth_value': '0.5'}]},
                        'confidence': 0.8,
                        'reasoning': 'Test evaluation',
                        'snapshot_id': 'test_snap',
                        'processed_at': 1234567890.0
                    }
                ]
            ),
            file_ids=[]
        )
        
        result = agent.generate_improvements(agent_input)
        
        # Verify the result includes evaluation context
        assert result.agent_type == "improver"
        assert result.operation == "generate_improvements"
        assert "evaluation_context" in result.result_content
        assert result.result_content["evaluation_context"]["content_evaluations_count"] == 1
        assert result.result_content["evaluation_context"]["formal_evaluations_count"] == 0
        assert result.result_content["evaluation_context"]["conclusion_proposition"] == "Test proposition"
        
        # Verify the GPT was called with the complete input including evaluation results
        mock_gpt_call.assert_called_once()
        call_args = mock_gpt_call.call_args[0][0]
        import json
        call_data = json.loads(call_args)  # Convert string back to dict
        assert 'agent_data' in call_data
        assert 'latest_results' in call_data['agent_data']
        assert call_data['agent_data']['latest_results'][0]['agent_type'] == 'content_evaluator'

    def test_improvement_agent_error_handling_with_specific_error_types(self):
        """Test that improvement agent provides specific error information for evaluation issues"""
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create agent input without evaluation results
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[self.test_step],
                assumptions=[],
                target_type="argument",
                target_content=None,
                latest_results=[]  # No evaluation results
            ),
            file_ids=[]
        )
        
        result = agent.generate_improvements(agent_input)
        
        # Verify error handling provides specific information
        assert result.confidence == 0.0
        assert "error" in result.result_content
        assert "error_type" in result.result_content
        assert result.result_content["error_type"] == "missing_evaluation_data"
        assert "suggestion" in result.result_content
        assert "Ensure content or formal evaluation agents have run" in result.result_content["suggestion"]

    def test_queue_improvement_agent_if_ready_uses_specialized_input_creation(self):
        """Test that queue_improvement_agent_if_ready uses the specialized input creation method"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Mock the should_queue_improvement_agent method to return True
        with patch.object(self.coordinator, '_should_queue_improvement_agent', return_value=True):
            # Mock the create_improvement_agent_input method
            with patch.object(self.coordinator, 'create_improvement_agent_input') as mock_create_input:
                mock_input = Mock()
                mock_create_input.return_value = mock_input
                
                # Mock get_active_tasks to return empty list
                with patch.object(self.coordinator, 'get_active_tasks', return_value=[]):
                    # Mock queue_task
                    with patch.object(self.coordinator, 'queue_task') as mock_queue_task:
                        self.coordinator.queue_improvement_agent_if_ready(
                            conversation_id, snapshot_id, self.argument_data
                        )
                        
                        # Verify that create_improvement_agent_input was called
                        mock_create_input.assert_called_once_with(
                            conversation_id, snapshot_id, self.argument_data, self.argument_data.file_ids
                        )
                        
                        # Verify that queue_task was called with the created input
                        mock_queue_task.assert_called_once_with(
                            agent_type='improver',
                            agent_input=mock_input
                        )
