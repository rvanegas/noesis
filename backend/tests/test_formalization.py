import pytest
import json
from unittest.mock import patch
from services.agents import FormalizationAgent
from services.agent_coordinator import coordinator
from schemas.step import Step
from schemas.agent_input import AgentInput, AgentData, FilteredAgentInput


class TestFormalizationAgent:
    """Test that the FormalizationAgent works correctly with the new structure"""
    
    def test_formalization_agent(self):
        """Test that formalization agent works correctly"""
        agent = FormalizationAgent(coordinator)
        
        # Mock the GPT response for formalization
        mock_response = {
            "formalizations": [
                {
                    "symbol": "A",
                    "ascii": "P(a)",
                    "json": {"type": "predicate", "name": "P", "args": [{"type": "constant", "name": "a"}]}
                },
                {
                    "symbol": "B",
                    "ascii": "forall x. (P(x) -> Q(x))",
                    "json": {"type": "quantifier", "quant": "forall", "var": {"type": "variable", "name": "x"}, "body": {"type": "binary", "op": "implies", "left": {"type": "predicate", "name": "P", "args": [{"type": "variable", "name": "x"}]}, "right": {"type": "predicate", "name": "Q", "args": [{"type": "variable", "name": "x"}]}}}
                },
                {
                    "symbol": "C",
                    "ascii": "Q(a)",
                    "json": {"type": "predicate", "name": "Q", "args": [{"type": "constant", "name": "a"}]}
                }
            ],
            "definitions": {
                "predicates": [
                    {"symbol": "P", "value": "is a man"},
                    {"symbol": "Q", "value": "is mortal"}
                ],
                "constants": [
                    {"symbol": "a", "value": "Socrates"}
                ]
            },
            "confidence": 0.9,
            "reasoning": "Consistent formalization using P for 'is a man' and Q for 'is mortal' across all propositions"
        }
        
        with patch('services.agents.agent_gpt_formalize') as mock_gpt:
            mock_gpt.call.return_value = json.dumps(mock_response)
            
            # Test data
            agent_data = AgentData(
                assumptions=[],
                argument=[
                    Step(symbol="A", proposition="Socrates is a man", justifiers=[], truth_score="", valid=""),
                    Step(symbol="B", proposition="All men are mortal", justifiers=[], truth_score="", valid=""),
                    Step(symbol="C", proposition="Socrates is mortal", justifiers=["A", "B"], truth_score="", valid="")
                ],
                latest_results=[],
                target_type="argument",
                target_content=None
            )
            agent_input = AgentInput(
                conversation_id="test_conversation",
                snapshot_id="test_snapshot_123",
                file_ids=[],
                agent_data=agent_data
            )
            
            # Create FilteredAgentInput for formalization
            filtered_input = FilteredAgentInput.for_formalization(agent_input)
            
            # Call the formalization agent
            result = agent.formalize_proposition(filtered_input)
            
            # Verify the result
            assert result.agent_type == "formalizer"
            assert result.operation == "formalize_proposition"
            assert result.result_content["formalization_mode"] == "proposition_to_logic"
            assert len(result.result_content["formalizations"]) == 3
            assert result.result_content["formalizations"][0]["symbol"] == "A"
            assert result.result_content["formalizations"][0]["ascii"] == "P(a)"
            # Check definitions using array structure
            predicates = {p["symbol"]: p["value"] for p in result.result_content["definitions"]["predicates"]}
            constants = {c["symbol"]: c["value"] for c in result.result_content["definitions"]["constants"]}
            assert predicates["P"] == "is a man"
            assert predicates["Q"] == "is mortal"
            assert constants["a"] == "Socrates"
            assert result.result_content["confidence"] == 0.9
            assert "Consistent formalization" in result.result_content["reasoning"]
            assert result.target_metadata["target_type"] == "argument"
            assert result.target_metadata["target_content"] is None


if __name__ == "__main__":
    pytest.main([__file__]) 