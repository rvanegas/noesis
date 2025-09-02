"""
Argument business logic service.
Handles state modification, GPT interactions, and complex argument operations.
"""

import json
import re
from typing import List, Tuple, Dict, Any

from core.utils import find_index, logger
from services.conversation import gpt_explain, gpt_gen_name  # gpt_justify, gpt_evaluate disabled
from services.agent_coordinator import coordinator
from schemas.arguments import Arguments, ArgumentsWithStep, ArgumentsWithProposition, ArgumentsWithStepAndProposition, ArgumentData
from schemas.step import Step


def clean_citations(proposition: str) -> str:
    """
    Clean citations from propositions by replacing non-ASCII brackets with ASCII brackets
    and keeping only the filename, removing numbers and dagger symbols.
    
    Example: "Mice are small【4:0†small.txt】." -> "Mice are small [small.txt]."
    """
    # Pattern to match citations like 【4:0†small.txt】 or similar
    # This matches the non-ASCII brackets 【】 and the dagger †, and captures the filename
    pattern = r'\u3010[^\u3011]*?([^\u2020]+)\u3011'
    
    def replace_citation(match):
        filename = match.group(1)
        if filename == "source":
            return ""
        return f" [{filename}]"

    replaced = re.sub(pattern, replace_citation, proposition)
    logger.debug(f"proposition: {proposition}")
    logger.debug(f"replaced...: {replaced}")
    return replaced


class ArgumentService:
    """Service for argument business logic and state modification"""
    
    def __init__(self, arguments: Arguments, snapshot_id: str):
        self.arguments = arguments
        self.snapshot_id = snapshot_id
    
    def next_symbol(self) -> str:
        """Picks next available A-Z in a natural order"""
        steps = (self.arguments.assumptions + self.arguments.argument)
        letters = [step.symbol for step in steps]
        if not all(isinstance(c, str) and len(c) == 1 and
            'A' <= c <= 'Z' for c in letters):
            raise ValueError("All elements must be single lowercase letters A-Z")
        seen = set(letters)
        if len(seen) == 0:
            return 'A'
        if len(seen) == 26:
            raise ValueError("All 26 letters are already present")
        if 'Z' not in seen:
            last = sorted(seen)[-1]
            return chr(ord(last)+1)
        for i in range(ord('A'), ord('Z') + 1):
            c = chr(i)
            if c not in seen:
                return c
        raise RuntimeError("something went wrong")

    def new_step(self, proposition: str) -> Step:
        """Make new step"""
        return Step(symbol=self.next_symbol(), proposition=proposition,
            justifiers=[], truth_score="", valid="")

    def subargument(self, arg: List[Step], conclusion: Step) -> Tuple[Dict[str, Any], List[Step]]:
        """Extract a few steps by way of a justifiers property"""
        new_arg = [s for s in arg if s.symbol in conclusion.justifiers]
        new_arg.append(conclusion)
        props = {
            "assumptions": [s.model_dump_json() for s in self.arguments.assumptions],
            "argument": [s.model_dump_json() for s in new_arg]
        }
        return props, new_arg

    def queue_argument_state_change(self):
        """Reactively queue agents for argument state changes"""
        # Prepare argument data for the reactive coordinator
        argument_data = ArgumentData(
            argument=self.arguments.argument,
            assumptions=self.arguments.assumptions,
            file_ids=self.arguments.file_ids
        )

        logger.debug(f"Queueing argument state change for conversation {argument_data}")
        
        # Use the reactive coordinator method
        coordinator.react_to_user_argument_change(
            self.arguments.conversation_id,
            self.snapshot_id,
            argument_data
        )

    def gptjson(self) -> str:
        """Arguments json to return to frontend"""
        return self.arguments.model_dump_json(include={
            "assumptions", "argument", "explanation"})

    def gptjsont(self) -> str:
        """Arguments json to return to frontend used by theses()"""
        return self.arguments.model_dump_json(include={"proposition"})


class ArgumentStepService(ArgumentService):
    """Service for argument operations involving specific steps"""
    
    def __init__(self, arguments_with_step: ArgumentsWithStep, snapshot_id: str):
        super().__init__(arguments_with_step, snapshot_id)
        self.arguments_with_step = arguments_with_step

    def insert_proposition(self, new_proposition: str) -> Step:
        """Add step and reference to it in indicated justifiers"""
        new_step = self.new_step(new_proposition)
        conclusion = self.arguments_with_step.arg[self.arguments_with_step.index]
        conclusion.justifiers.append(new_step.symbol)
        self.arguments_with_step.arg.insert(self.arguments_with_step.index, new_step)
        # Queue analysis and discovery for the argument state change
        self.queue_argument_state_change()
        return conclusion

    def remove(self) -> str:
        """Remove step and adjust justifiers and evaluations accordingly"""
        if self.arguments_with_step.loc != "assumptions":
            # Clean up justifiers for this step
            step_to_remove = self.arguments_with_step.arg[self.arguments_with_step.index]
            inferences_to = [s for s in self.arguments_with_step.arg if step_to_remove.symbol in s.justifiers]
            
            for step in inferences_to:
                step.justifiers.remove(step_to_remove.symbol)
                # Add the removed step's justifiers to the dependent step
                step.justifiers.extend(step_to_remove.justifiers)
        
        del self.arguments_with_step.arg[self.arguments_with_step.index]
        # Queue analysis and discovery for the argument state change
        self.queue_argument_state_change()
        return self.gptjson()

    def assume(self) -> str:
        """Move step into assumptions and adjust evaluations accordingly"""
        if self.arguments_with_step.loc == "assumptions":
            raise ValueError("already assumed")
        if len(self.arguments_with_step.arg[self.arguments_with_step.index].justifiers) != 0:
            raise ValueError("cannot assume justified proposition")
        self.arguments_with_step.arg[self.arguments_with_step.index].truth_score = "1.0"
        self.arguments_with_step.assumptions.append(self.arguments_with_step.arg[self.arguments_with_step.index])
        del self.arguments_with_step.arg[self.arguments_with_step.index]
        # Queue analysis and discovery for the argument state change
        self.queue_argument_state_change()
        return self.gptjson()

    def explain(self) -> str:
        """Explain the 'valid' property and formalize the propositions."""
        assert len(self.arguments_with_step.arg[self.arguments_with_step.index].justifiers) != 0
        props, new_arg = self.subargument(self.arguments_with_step.arg, self.arguments_with_step.arg[self.arguments_with_step.index])
        response = gpt_explain.call(json.dumps(props), self.arguments_with_step.file_ids)
        content = json.loads(response)
        
        self.arguments_with_step.explanation = content["explanation"]
        return self.gptjson()

    def reject_formalization(self) -> str:
        """Remove formalization from a step and trigger re-formalization"""
        # Remove the formalization from the specified step
        step = self.arguments_with_step.arg[self.arguments_with_step.index]
        # Set formalization to None instead of deleting the attribute
        step.formalization = None
        
        # Queue analysis and discovery for the argument state change
        # This will automatically trigger the formalization agent
        self.queue_argument_state_change()
        
        return self.gptjson()

    def endorse_formalization(self) -> str:
        """Endorse a formalization and potentially trigger formal evaluator"""
        # Update the endorsement status of the formalization
        step = self.arguments_with_step.arg[self.arguments_with_step.index]
        if step.formalization:
            step.formalization.endorsed = True
        
        # Only trigger formal evaluator check, not other agents
        # Create argument data for formal evaluator check
        argument_data = ArgumentData(
            argument=self.arguments_with_step.arg,
            assumptions=self.arguments_with_step.assumptions,
            file_ids=self.arguments_with_step.file_ids
        )
        
        # Check if formal evaluator should be triggered
        coordinator.queue_formal_evaluator_if_ready(
            self.arguments_with_step.conversation_id,
            self.snapshot_id,
            argument_data
        )
        
        return self.gptjson()


class ArgumentPropositionService(ArgumentService):
    """Service for argument operations involving propositions"""
    
    def __init__(self, arguments_with_proposition: ArgumentsWithProposition, snapshot_id: str):
        super().__init__(arguments_with_proposition, snapshot_id)
        self.arguments_with_proposition = arguments_with_proposition

    def argue(self) -> str:
        """Add proposition as first argument step"""
        assert len(self.arguments_with_proposition.arg) == 0
        new_step = self.new_step(self.arguments_with_proposition.proposition)
        self.arguments_with_proposition.argument.append(new_step)
        logger.debug(f"arg: {self.arguments_with_proposition.argument}")
        # Queue analysis and discovery for the argument state change
        self.queue_argument_state_change()
        logger.debug(f"gptjson: {self.gptjson()}")
        return self.gptjson()

    def gen_name(self) -> str:
        """Generate name from proposition"""
        return gpt_gen_name.call(self.gptjsont(), self.arguments_with_proposition.file_ids)


class ArgumentStepAndPropositionService(ArgumentStepService, ArgumentPropositionService):
    """Service for argument operations involving both steps and propositions"""
    
    def __init__(self, arguments_with_step_and_proposition: ArgumentsWithStepAndProposition, snapshot_id: str):
        ArgumentStepService.__init__(self, arguments_with_step_and_proposition, snapshot_id)
        ArgumentPropositionService.__init__(self, arguments_with_step_and_proposition, snapshot_id)
        self.arguments_with_step_and_proposition = arguments_with_step_and_proposition

    def user_justify(self) -> str:
        """Add step using proposition attr and adjust justifiers and evaluations accordingly"""
        assert self.arguments_with_step_and_proposition.loc in ["argument"]
        new_step = self.new_step(self.arguments_with_step_and_proposition.proposition)
        conclusion = self.arguments_with_step_and_proposition.arg[self.arguments_with_step_and_proposition.index]
        self.arguments_with_step_and_proposition.arg.insert(self.arguments_with_step_and_proposition.index, new_step)
        conclusion.justifiers.append(new_step.symbol)
        # Queue analysis and discovery for the argument state change
        self.queue_argument_state_change()
        return self.gptjson()
