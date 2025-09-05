import json
# import time
from typing import Dict, Any, List
from dataclasses import dataclass

from services.agent_prompts import agent_gpt_justify, agent_gpt_evaluate_content, agent_gpt_evaluate_form, agent_gpt_formalize, agent_gpt_improvement
from services.conversation import gpt_gen_name
from schemas.agent_input import AgentInput, FilteredAgentInput

from core.utils import logger


@dataclass
class AgentResult:
    """Result from an agent operation"""
    agent_type: str
    operation: str
    result_content: Dict[str, Any]  # The actual output from the agent
    confidence: float = 0.0
    reasoning: str = ""
    target_metadata: Dict[str, Any] = None  # Metadata about what was targeted
    snapshot_id: str = ""  # Links result to specific snapshot
    
    def __post_init__(self):
        if self.target_metadata is None:
            self.target_metadata = {}


class ContentEvaluationAgent:
    """Agent that evaluates the truth and validity of argument propositions"""
    
    def __init__(self, coordinator):
        if coordinator is None:
            raise ValueError("ContentEvaluationAgent requires a coordinator")
        self.name = "content_evaluator"
        self.coordinator = coordinator
    
    def evaluate_propositions(self, agent_input: FilteredAgentInput) -> AgentResult:
        """Evaluate the truth and validity of argument propositions"""
        try:
            # logger.info(f"ContentEvaluationAgent starting task for conversation: {agent_input.conversation_id}")
            # logger.debug(f"ContentEvaluationAgent starting task with data: {agent_input}")
            
            # Use direct access for FilteredAgentInput
            file_ids = agent_input.file_ids
            payload = agent_input.model_dump()
            arg_for_result = agent_input.agent_data.argument
            assumptions_for_result = agent_input.agent_data.assumptions

            # Pass the data directly to the agent
            evaluation_response = agent_gpt_evaluate_content.call(json.dumps(payload), file_ids)
            evaluation_result = json.loads(evaluation_response)
            
            # logger.info(f"ContentEvaluationAgent completed")
            # if recommendations:
            #     logger.info(f"ContentEvaluationAgent provided {len(recommendations)} recommendations: {recommendations}")
            
            result = AgentResult(
                agent_type=self.name,
                operation="evaluate_propositions",
                result_content={
                    **evaluation_result,
                    "evaluation_mode": "content_truth_coherence",
                    "argument": arg_for_result,
                    "assumptions": assumptions_for_result
                },
                target_metadata={
                    'target_type': 'argument'
                },
                snapshot_id=agent_input.snapshot_id
            )
            
            # logger.debug(f"ContentEvaluationAgent task completed successfully. Output: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Content evaluator agent error: {e}")
            result = AgentResult(
                agent_type=self.name,
                operation="evaluate_propositions",
                result_content={"error": str(e)},
                confidence=0.0,
                reasoning=f"Error in content evaluation: {e}",
                target_metadata={
                    'target_type': 'argument'
                },
                snapshot_id=agent_input.snapshot_id
            )
            # logger.debug(f"ContentEvaluationAgent task failed. Output: {result}")
            return result


class FormalEvaluatorAgent:
    """Agent that evaluates only the logical validity of formalized arguments"""
    
    def __init__(self, coordinator):
        if coordinator is None:
            raise ValueError("FormalEvaluatorAgent requires a coordinator")
        self.name = "form_evaluator"
        self.coordinator = coordinator

    def evaluate_propositions(self, agent_input: FilteredAgentInput) -> AgentResult:
        """Evaluate only the logical validity of formalized arguments"""
        try:
            # logger.info(f"FormalEvaluatorAgent starting task for conversation: {agent_input.conversation_id}")
            # logger.debug(f"FormalEvaluatorAgent starting task with data: {agent_input}")
            
            # Use FilteredAgentInput to focus on formal logic only
            filtered_input = FilteredAgentInput.for_formal_evaluation(agent_input)
            file_ids = filtered_input.file_ids
            payload = filtered_input.model_dump()
            arg_for_result = filtered_input.agent_data.argument
            assumptions_for_result = filtered_input.agent_data.assumptions
            
            # Pass the data directly to the agent
            evaluation_response = agent_gpt_evaluate_form.call(json.dumps(payload), file_ids)
            evaluation_result = json.loads(evaluation_response)
            
            # logger.info(f"FormalEvaluatorAgent completed")
            
            result = AgentResult(
                agent_type=self.name,
                operation="evaluate_propositions",
                result_content={
                    **evaluation_result,
                    "evaluation_mode": "formal_validity",
                    "argument": arg_for_result,
                    "assumptions": assumptions_for_result
                },
                target_metadata={
                    'target_type': 'argument'
                },
                snapshot_id=agent_input.snapshot_id
            )
            
            # logger.debug(f"FormalEvaluatorAgent task completed successfully. Output: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Formal evaluator agent error: {e}")
            result = AgentResult(
                agent_type=self.name,
                operation="evaluate_propositions",
                result_content={"error": str(e)},
                confidence=0.0,
                reasoning=f"Error in form evaluation: {e}",
                target_metadata={
                    'target_type': 'argument'
                },
                snapshot_id=agent_input.snapshot_id
            )
            # logger.debug(f"FormalEvaluatorAgent task failed. Output: {result}")
            return result
    

class FormalizationAgent:
    """Agent that formalizes propositions into logical notation"""
    
    def __init__(self, coordinator):
        if coordinator is None:
            raise ValueError("FormalizationAgent requires a coordinator")
        self.name = "formalizer"
        self.coordinator = coordinator
    
    def _get_existing_formalizations(self, conversation_id: str) -> List[Dict[str, Any]]:
        """Get existing formalizations for this conversation"""
        try:
            existing_results = self.coordinator.get_conversation_results(conversation_id)
            formalizations = []
            
            for result in existing_results:
                if result.agent_type == 'formalizer':
                    formalizations.append(result.result_content)
            
            return formalizations
            
        except Exception as e:
            logger.error(f"Error getting existing formalizations: {e}")
            return []
    
    def formalize_proposition(self, agent_input: FilteredAgentInput) -> AgentResult:
        """Formalize a proposition into logical notation"""
        try:
            # logger.info(f"FormalizationAgent starting task for conversation: {agent_input.conversation_id}")
            # logger.debug(f"FormalizationAgent starting task with data: {agent_input}")
            
            # Use direct access for FilteredAgentInput
            file_ids = agent_input.file_ids
            payload = agent_input.model_dump()
            arg_for_result = agent_input.agent_data.argument
            assumptions_for_result = agent_input.agent_data.assumptions
            
            # Validate that we have argument data to formalize
            if not agent_input.agent_data.argument:
                raise ValueError("No argument provided for formalization")
            
            # Check if there are any steps that need formalization
            steps_needing_formalization = []
            for step in agent_input.agent_data.argument:
                if not step.formalization or not step.formalization.endorsed:
                    steps_needing_formalization.append(step)
            
            # If all steps have endorsed formalizations, return early
            if not steps_needing_formalization:
                result = AgentResult(
                    agent_type=self.name,
                    operation="formalize_proposition",
                    result_content={
                        "formalizations": [],
                        "definitions": {},
                        "confidence": 1.0,
                        "reasoning": "All steps already have endorsed formalizations - no new formalizations needed",
                        "formalization_mode": "proposition_to_logic",
                        "argument": arg_for_result,
                        "assumptions": assumptions_for_result
                    },
                    confidence=1.0,
                    reasoning="All steps have endorsed formalizations",
                    target_metadata={
                        'target_type': 'argument',
                        'target_content': agent_input.agent_data.target_content
                    },
                    snapshot_id=agent_input.snapshot_id
                )
                return result
            
            # Keep all steps in the payload so the agent can see endorsed formalizations for consistency
            # The agent will only generate new formalizations for steps that need them
            
            # logger.debug(f"FormalizationAgent sending data: {payload}")
            
            # Pass the data directly to the agent
            formalization_response = agent_gpt_formalize.call(json.dumps(payload), file_ids)
            formalization_result = json.loads(formalization_response)
            
            # Debug logging
            # logger.info(f"FormalizationAgent response: {formalization_result}")
            # logger.info(f"FormalizationAgent response keys: {list(formalization_result.keys())}")
            # if 'formalizations' in formalization_result:
            #     logger.info(f"FormalizationAgent formalizations: {formalization_result['formalizations']}")
            # else:
            #     logger.warning("FormalizationAgent response missing 'formalizations' key")
            
            # Extract formalization results
            confidence = formalization_result.get("confidence", 0.0)
            reasoning = formalization_result.get("reasoning", "")
            
            # logger.info(f"FormalizationAgent completed - Proposition: '{proposition[:50]}...', Confidence: {confidence:.2f}")
            
            result = AgentResult(
                agent_type=self.name,
                operation="formalize_proposition",
                result_content={
                    **formalization_result,
                    "formalization_mode": "proposition_to_logic",
                    "argument": arg_for_result,
                    "assumptions": assumptions_for_result
                },
                target_metadata={
                    'target_type': 'argument',
                    'target_content': agent_input.agent_data.target_content
                },
                snapshot_id=agent_input.snapshot_id
            )
            
            # logger.info(f"FormalizationAgent task completed successfully. Output: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Formalization agent error: {e}")
            result = AgentResult(
                agent_type=self.name,
                operation="formalize_proposition",
                result_content={"error": str(e)},
                confidence=0.0,
                reasoning=f"Error in formalization: {e}",
                target_metadata={
                    'target_type': 'argument',
                    'target_content': agent_input.agent_data.target_content or ''
                },
                snapshot_id=agent_input.snapshot_id
            )
            # logger.debug(f"FormalizationAgent task failed. Output: {result}")
            return result
    



class ImprovementAgent:
    """Agent that provides intelligent recommendations for argument enhancement based on evaluation results"""
    
    def __init__(self, coordinator):
        if coordinator is None:
            raise ValueError("ImprovementAgent requires a coordinator")
        self.name = "improver"
        self.coordinator = coordinator
    
    def generate_improvements(self, agent_input: AgentInput) -> AgentResult:
        """Generate improvement recommendations based on evaluation results"""
        try:
            # logger.info(f"ImprovementAgent starting task for conversation: {agent_input.conversation_id}")
            # logger.debug(f"ImprovementAgent starting task with data: {agent_input}")
            
            # Get file_ids from task data
            file_ids = agent_input.file_ids
            
            # Validate that we have the required evaluation results
            if not agent_input.agent_data.latest_results:
                raise ValueError("Improvement agent requires at least content or formal evaluation results")
            
            # Extract evaluation results from latest_results
            latest_results = agent_input.agent_data.latest_results
            content_evaluations = [r for r in latest_results if r['agent_type'] == 'content_evaluator']
            formal_evaluations = [r for r in latest_results if r['agent_type'] == 'form_evaluator']
            
            # Check if we have sufficient evaluation data
            if not content_evaluations and not formal_evaluations:
                raise ValueError("Improvement agent requires at least content or formal evaluation results")
            
            # Prepare the input data for the improvement agent
            # The agent needs evaluation results, conclusion information, and current scores
            payload = agent_input.model_dump()
            
            # Pass the data directly to the agent
            improvement_response = agent_gpt_improvement.call(json.dumps(payload), file_ids)
            improvement_result = json.loads(improvement_response)
            
            # logger.info(f"ImprovementAgent completed")
            
            result = AgentResult(
                agent_type=self.name,
                operation="generate_improvements",
                result_content={
                    **improvement_result,
                    "improvement_mode": "evaluation_driven",
                    "argument": agent_input.agent_data.argument,
                    "assumptions": agent_input.agent_data.assumptions,
                    "evaluation_context": {
                        "content_evaluations_count": len(content_evaluations),
                        "formal_evaluations_count": len(formal_evaluations),
                        "conclusion_proposition": agent_input.agent_data.argument[-1].proposition if agent_input.agent_data.argument else None,
                        "total_evaluations": len(agent_input.agent_data.latest_results)
                        # Note: current_conclusion_scores available in argument_data.argument[-1]
                    }
                },
                confidence=0.8,  # Default confidence for improvement recommendations
                reasoning="Generated improvement recommendations based on evaluation results",
                target_metadata={
                    'target_type': 'argument',
                    'target_content': agent_input.agent_data.target_content
                },
                snapshot_id=agent_input.snapshot_id
            )
            
            # logger.debug(f"ImprovementAgent task completed successfully. Output: {result}")
            return result
            
        except Exception as e:
            logger.error(f"Improvement agent error: {e}")
            
            # Provide more specific error information for evaluation-related issues
            error_content = {"error": str(e)}
            if "evaluation results" in str(e).lower():
                error_content["error_type"] = "missing_evaluation_data"
                error_content["suggestion"] = "Ensure content or formal evaluation agents have run before improvement agent"
            elif "insufficient" in str(e).lower():
                error_content["error_type"] = "insufficient_data"
                error_content["suggestion"] = "Wait for evaluation agents to complete their analysis"
            
            result = AgentResult(
                agent_type=self.name,
                operation="generate_improvements",
                result_content=error_content,
                confidence=0.0,
                reasoning=f"Error in improvement generation: {e}",
                target_metadata={
                    'target_type': 'argument',
                    'target_content': agent_input.agent_data.target_content or ''
                },
                snapshot_id=agent_input.snapshot_id
            )
            # logger.debug(f"ImprovementAgent task failed. Output: {result}")
            return result


class NameGenerationAgent:
    """Agent that generates conversation names from propositions"""
    
    def __init__(self, coordinator):
        if coordinator is None:
            raise ValueError("NameGenerationAgent requires a coordinator")
        self.name = "name_generator"
        self.coordinator = coordinator
    
    def generate_name(self, agent_input: AgentInput) -> AgentResult:
        """Generate a conversation name from the proposition"""
        try:
            # Extract the proposition from the agent input
            proposition = agent_input.agent_data.target_content
            # logger.info(f"🔤 NameGenerationAgent: Starting name generation for conversation {agent_input.conversation_id}")
            # logger.info(f"🔤 NameGenerationAgent: Proposition: {proposition}")
            # logger.info(f"🔤 NameGenerationAgent: Assumptions: {len(agent_input.agent_data.assumptions)} items")
            # logger.info(f"🔤 NameGenerationAgent: Argument: {len(agent_input.agent_data.argument)} items")
            
            # Create the input format expected by gpt_gen_name
            # Convert Step objects to dictionaries for JSON serialization
            gpt_input = {
                "assumptions": [step.model_dump() for step in agent_input.agent_data.assumptions],
                "argument": [step.model_dump() for step in agent_input.agent_data.argument],
                "proposition": proposition
            }
            
            # Call the GPT model
            # logger.info(f"🔤 NameGenerationAgent: Calling gpt_gen_name.call()")
            prompt_json = json.dumps(gpt_input, indent=2)
            # logger.info(f"🔤 NameGenerationAgent: GPT input: {prompt_json}")
            name_response = gpt_gen_name.call(prompt_json, agent_input.file_ids)
            # logger.info(f"🔤 NameGenerationAgent: Generated name response: {name_response}")
            
            # Parse the JSON response to extract the name
            name_data = json.loads(name_response)
            name = name_data.get('name', '')
            # logger.info(f"🔤 NameGenerationAgent: Extracted name: {name}")
            
            result = AgentResult(
                agent_type="name_generator",
                operation="generate_name",
                result_content={"name": name},
                confidence=1.0,
                reasoning="Generated conversation name from proposition",
                target_metadata={"proposition": proposition}
            )
            
            return result
            
        except Exception as e:
            logger.error(f"NameGenerationAgent task failed: {e}")
            result = AgentResult(
                agent_type="name_generator",
                operation="generate_name",
                result_content={"error": str(e)},
                confidence=0.0,
                reasoning=f"Name generation failed: {str(e)}",
                target_metadata={"proposition": agent_input.agent_data.target_content if agent_input.agent_data.target_content else None}
            )
            return result



