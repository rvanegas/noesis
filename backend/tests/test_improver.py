"""Test the ImprovementAgent functionality"""

import pytest
from unittest.mock import Mock, patch
from services.agents import ImprovementAgent
from schemas.agent_input import AgentInput, AgentData
from schemas.step import Step


class TestImprovementAgent:
    """Test that the ImprovementAgent works correctly"""

    def test_improvement_agent_initialization(self):
        """Test that improvement agent initializes correctly"""
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        assert agent.name == "improver"
        assert agent.coordinator == coordinator

    def test_improvement_agent_requires_coordinator(self):
        """Test that improvement agent requires a coordinator"""
        with pytest.raises(ValueError, match="ImprovementAgent requires a coordinator"):
            ImprovementAgent(None)

    @patch('services.agent_prompts.agent_gpt_improvement.call')
    def test_generate_improvements_success(self, mock_gpt_call):
        """Test that improvement agent generates improvements successfully"""
        # Mock the GPT response
        mock_gpt_call.return_value = '{"recommendations": [{"id": "rec_001", "reasoning": "Test reasoning", "confidence": 0.8, "impact": "high", "target_proposition": "A", "expected_conclusion_improvement": {"truth_score_improvement": 0.3, "content_validity_improvement": 0.2, "formal_validity_improvement": 0.1, "reasoning": "Test improvement"}, "propositions": [{"symbol": "B", "proposition": "Test proposition", "type": "new", "placement": "argument", "justification_suggestions": ["Test justification"]}]}]}'
        
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create test input
        step = Step(
            symbol="A",
            proposition="Test proposition",
            justifiers=[],
            truth_score="0.5",
            content_validity="0.4",
            formal_validity="0.3"
        )
        
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[step],
                assumptions=[],
                target_type="argument",
                target_content=None
            ),
            file_ids=[]
        )
        
        result = agent.generate_improvements(agent_input)
        
        # Verify the result structure
        assert result.agent_type == "improver"
        assert result.operation == "generate_improvements"
        assert result.snapshot_id == "test_snap"
        assert result.confidence == 0.8
        assert "improvement_mode" in result.result_content
        assert result.result_content["improvement_mode"] == "evaluation_driven"
        assert "recommendations" in result.result_content
        
        # Verify the GPT was called
        mock_gpt_call.assert_called_once()

    @patch('services.agent_prompts.agent_gpt_improvement.call')
    def test_generate_improvements_error_handling(self, mock_gpt_call):
        """Test that improvement agent handles errors gracefully"""
        # Mock the GPT to raise an exception
        mock_gpt_call.side_effect = Exception("GPT API error")
        
        coordinator = Mock()
        agent = ImprovementAgent(coordinator)
        
        # Create test input
        step = Step(
            symbol="A",
            proposition="Test proposition",
            justifiers=[],
            truth_score="0.5",
            content_validity="0.4",
            formal_validity="0.3"
        )
        
        agent_input = AgentInput(
            conversation_id="test_conv",
            snapshot_id="test_snap",
            agent_data=AgentData(
                argument=[step],
                assumptions=[],
                target_type="argument",
                target_content=None
            ),
            file_ids=[]
        )
        
        result = agent.generate_improvements(agent_input)
        
        # Verify error handling
        assert result.agent_type == "improver"
        assert result.operation == "generate_improvements"
        assert result.confidence == 0.0
        assert "error" in result.result_content
        assert "GPT API error" in result.result_content["error"]
        assert "Error in improvement generation" in result.reasoning
