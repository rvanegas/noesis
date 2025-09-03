import threading
import time
import uuid
from queue import Queue
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from datetime import datetime

from schemas import agent_input
from core.utils import logger
from services.agents import ArgumentBuilderAgent, ContentEvaluationAgent, FormalEvaluatorAgent, FormalizationAgent, RewriterAgent, ImprovementAgent
from schemas.agent_input import AgentInput, AgentData, FilteredAgentInput
from schemas.arguments import ArgumentData

# TTL configuration
AGENT_RESULT_TTL_SECONDS = 3 * 24 * 60 * 60  # 3 days in seconds


@dataclass
class TargetMetadata:
    """Metadata about what an agent result targets"""
    target_type: str  # 'argument', 'proposition', etc.
    target_content: str  # The specific content being targeted


@dataclass
class StoredAgentResult:
    """Stored agent result with all necessary fields for result management"""
    agent_type: str
    operation: str
    result_content: Dict[str, Any]
    confidence: float
    reasoning: str
    target_metadata: TargetMetadata
    snapshot_id: str
    processed_at: float


@dataclass
class AgentTask:
    """Represents a task for an agent to process"""
    id: str
    agent_type: str  # 'builder', 'content_evaluator', 'form_evaluator', 'formalizer', 'rewriter'
    agent_input: AgentInput
    status: str = 'pending'  # 'pending', 'running', 'completed', 'failed'
    priority: int = 0
    created_at: float = None
    completed_at: Optional[float] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def __post_init__(self):
        if self.created_at is None:
            self.created_at = time.time()
    



class AgentResultManager:
    """Manages agent results with disciplined cleanup and TTL maintenance"""
    
    def __init__(self):
        self.results_by_conversation: Dict[str, List[StoredAgentResult]] = {}
        self.conversation_timestamps: Dict[str, float] = {}  # Track last activity per conversation
    
    def add_result(self, conversation_id: str, result: StoredAgentResult):
        """Add a new result and clean up outdated ones"""
        if conversation_id not in self.results_by_conversation:
            self.results_by_conversation[conversation_id] = []
        
        # Clean up outdated results before adding the new one
        self._cleanup_outdated_results(conversation_id, result)
        
        # Check if this form evaluator result should be added
        if result.agent_type == 'form_evaluator':
            if not self._should_add_form_evaluator_result(conversation_id, result):
                # Don't add the result if formalization is incomplete
                return
        
        # Add the new result and update conversation timestamp
        self.results_by_conversation[conversation_id].append(result)
        self.conversation_timestamps[conversation_id] = time.time()
    
    def _cleanup_outdated_results(self, conversation_id: str, new_result: StoredAgentResult):
        """Remove outdated results based on the new result"""
        results = self.results_by_conversation[conversation_id]
        agent_type = new_result.agent_type
        operation = new_result.operation
        
        # Get the proposition or argument identifier for this result
        target_id = self._get_result_target_id(new_result)
        
        # Remove outdated results of the same type for the same target
        results[:] = [
            result for result in results
            if not self._is_outdated_result(result, agent_type, operation, target_id)
        ]
        

    
    def _get_result_target_id(self, result: StoredAgentResult) -> str:
        """Get a unique identifier for what this result targets"""
        agent_type = result.agent_type
        target_metadata = result.target_metadata
        target_type = target_metadata.target_type
        target_content = target_metadata.target_content
        snapshot_id = result.snapshot_id
        
        if agent_type == 'builder':
            # Builder targets a specific proposition
            return f"builder:{target_type}:{target_content}:{snapshot_id}"
        
        elif agent_type == 'formalizer':
            # Formalizer targets a specific proposition
            return f"formalizer:{target_type}:{target_content}:{snapshot_id}"
        
        elif agent_type in ['content_evaluator', 'form_evaluator']:
            # Evaluators target the entire argument as a whole
            return f"{agent_type}:{target_type}:{snapshot_id}"
        
        elif agent_type == 'rewriter':
            # Rewriter targets a specific proposition
            return f"rewriter:{target_type}:{target_content}:{snapshot_id}"
        
        # Fallback to using the entire result as identifier
        return f"{agent_type}:{hash(str(result))}:{snapshot_id}"
    
    def _is_outdated_result(self, result: StoredAgentResult, new_agent_type: str, 
                           new_operation: str, target_id: str) -> bool:
        """Check if a result is outdated compared to a new result"""
        agent_type = result.agent_type
        operation = result.operation
        
        # If it's the same agent type and operation, check if it targets the same thing
        if agent_type == new_agent_type and operation == new_operation:
            result_target_id = self._get_result_target_id(result)
            return result_target_id == target_id
        
        return False
    
    def _should_add_form_evaluator_result(self, conversation_id: str, result: StoredAgentResult) -> bool:
        """Check if a form evaluator result should be added"""
        # Get all formalizations for this conversation
        formalizations = []
        for existing_result in self.results_by_conversation.get(conversation_id, []):
            if existing_result.agent_type == 'formalizer':
                formalizations.append(existing_result)
        
        # Only add form evaluator result if we have formalizations
        return len(formalizations) > 0
    
    def get_results(self, conversation_id: str) -> List[StoredAgentResult]:
        """Get all results for a conversation"""
        results = self.results_by_conversation.get(conversation_id, [])
        
        if not results:
            return []
        
        # Update conversation timestamp on activity
        self.conversation_timestamps[conversation_id] = time.time()
        
        return results
    
    def get_latest_results(self, conversation_id: str, snapshot_id: str) -> List[StoredAgentResult]:
        """Retrieve latest agent results for a conversation/snapshot context"""
        all_results = self.get_results(conversation_id)
        
        if not all_results:
            return []
        
        # Filter to only results <= current snapshot
        # Convert snapshot_id to integer for comparison (frontend guarantees this is parseable)
        current_snapshot = int(snapshot_id)
        filtered_results = []
        for result in all_results:
            result_snapshot = int(result.snapshot_id)
            if result_snapshot <= current_snapshot:
                filtered_results.append(result)
        all_results = filtered_results
        
        # Group results by agent type and keep only the latest for each type
        latest_results = {}
        for result in all_results:
            agent_type = result.agent_type
            if agent_type not in latest_results or result.processed_at > latest_results[agent_type].processed_at:
                latest_results[agent_type] = result
        
        return list(latest_results.values())
    
    def get_results_by_target_type(self, conversation_id: str, target_type: str, snapshot_id: str) -> List[StoredAgentResult]:
        """Get results filtered by target type (argument vs proposition level)"""
        latest_results = self.get_latest_results(conversation_id, snapshot_id)
        
        return [
            result for result in latest_results
            if result.target_metadata.target_type == target_type
        ]
    
    def cleanup_conversation(self, conversation_id: str):
        """Clean up all results for a conversation"""
        if conversation_id in self.results_by_conversation:
            del self.results_by_conversation[conversation_id]
        if conversation_id in self.conversation_timestamps:
            del self.conversation_timestamps[conversation_id]
        logger.debug(f"Cleaned up all results for conversation {conversation_id}")
    
    def cleanup_expired_conversations(self) -> int:
        """Clean up expired conversations and return count of removed conversations"""
        current_time = time.time()
        expired_conversations = []
        
        for conversation_id, timestamp in self.conversation_timestamps.items():
            if current_time - timestamp > AGENT_RESULT_TTL_SECONDS:
                expired_conversations.append(conversation_id)
        
        # Remove expired conversations
        for conversation_id in expired_conversations:
            del self.results_by_conversation[conversation_id]
            del self.conversation_timestamps[conversation_id]
        
        if expired_conversations:
            logger.info(f"Cleaned up {len(expired_conversations)} expired conversations")
        
        return len(expired_conversations)
    
    def get_formatted_results(self, conversation_id: str, snapshot_id: str) -> Dict[str, Any]:
        """Get formatted agent results for API response"""
        from services.agent_coordinator import coordinator
        
        # Get latest results
        all_results = self.get_latest_results(conversation_id, snapshot_id)
        
        # Group results by agent type
        results_by_agent = self._group_results_by_agent(all_results)
        
        # Check if all tasks for this conversation/snapshot are complete
        tasks_complete = coordinator.are_conversation_tasks_complete(conversation_id, snapshot_id)
        
        # Get active tasks for this conversation
        active_tasks = coordinator.get_active_tasks()
        conversation_active_tasks = [
            task for task in active_tasks 
            if task.agent_input.conversation_id == conversation_id and 
               task.agent_input.snapshot_id == snapshot_id
        ]
        
        return {
            "conversation_id": conversation_id,
            "snapshot_id": snapshot_id,
            "results_by_agent": results_by_agent,
            "total_count": len(all_results),
            "agent_types": list(results_by_agent.keys()),
            "tasks_complete": tasks_complete,
            "active_tasks": [
                {
                    "task_id": task.id,
                    "agent_type": task.agent_type,
                    "status": task.status,
                    "conversation_id": task.agent_input.conversation_id,
                    "snapshot_id": task.agent_input.snapshot_id
                }
                for task in conversation_active_tasks
            ],
            "active_task_count": len(conversation_active_tasks)
        }
    
    def _group_results_by_agent(self, all_results: List[StoredAgentResult]) -> Dict[str, List[Dict[str, Any]]]:
        """Group agent results by agent type and convert to API format"""
        results_by_agent = {}
        
        for result in all_results:
            agent_type = result.agent_type
            if agent_type not in results_by_agent:
                results_by_agent[agent_type] = []
            
            # Convert StoredAgentResult to dict for API response
            result_dict = {
                'agent_type': result.agent_type,
                'operation': result.operation,
                'result_content': result.result_content,
                'confidence': result.confidence,
                'reasoning': result.reasoning,
                'target_metadata': {
                    'target_type': result.target_metadata.target_type,
                    'target_content': result.target_metadata.target_content
                },
                'snapshot_id': result.snapshot_id,
                'processed_at': result.processed_at
            }
            results_by_agent[agent_type].append(result_dict)
        
        return results_by_agent
    
    def get_active_tasks_formatted(self, conversation_id: str) -> Dict[str, Any]:
        """Get active tasks for the conversation in formatted API response"""
        from services.agent_coordinator import coordinator
        
        active_tasks = coordinator.get_active_tasks()
        
        # Filter tasks by conversation_id
        filtered_tasks = [
            task for task in active_tasks 
            if task.agent_input.conversation_id == conversation_id
        ]
        
        return {
            "active_tasks": [
                {
                    "task_id": task.id,
                    "agent_type": task.agent_type,
                    "status": task.status,
                    "conversation_id": task.agent_input.conversation_id
                }
                for task in filtered_tasks
            ],
            "count": len(filtered_tasks)
        }


class AgentCoordinator:
    """Manages background agent tasks using threading"""
    
    def __init__(self):
        self.task_queue = []  # Simple list instead of Queue
        self.task_queue_lock = threading.Lock()  # Thread safety for list operations
        self.workers = []
        self.running = True
        self.result_manager = AgentResultManager()  # Use the new result manager
        self.task_history = {}   # Store task history by task_id
        self.most_recent_conversation: Optional[str] = None  # Track most recently accessed conversation
        self.most_recent_snapshot: Optional[int] = None  # Track most recently accessed snapshot
        
        # Create agents with coordinator dependency injected
        self.agents = {
            'builder': ArgumentBuilderAgent(self),
            'content_evaluator': ContentEvaluationAgent(self),
            'form_evaluator': FormalEvaluatorAgent(self),
            'formalizer': FormalizationAgent(self),
            'rewriter': RewriterAgent(self),
            'improver': ImprovementAgent(self)
        }
        
        # Start background workers
        self._start_workers()
        logger.info("AgentCoordinator initialized with background workers")
    
    def _start_workers(self):
        """Start background worker threads for each agent type"""
        agent_types = ['builder', 'content_evaluator', 'form_evaluator', 'formalizer', 'rewriter', 'improver']
        
        for agent_type in agent_types:
            worker = threading.Thread(
                target=self._worker_loop, 
                args=(agent_type,),
                name=f"agent_worker_{agent_type}"
            )
            worker.daemon = True
            worker.start()
            self.workers.append(worker)
            # logger.info(f"Started worker thread for {agent_type} agent")
    
    def _worker_loop(self, agent_type: str):
        """Main worker loop for processing tasks"""
        # logger.info(f"Worker {agent_type} started")
        
        while self.running:
            try:
                # Get task from queue with prioritization
                task = self._get_next_task_for_agent(agent_type)
                
                if task:
                    # logger.info(f"Worker {agent_type} processing task {task.id}")
                    self._process_task(task)
                    
            except Exception as e:
                # Queue timeout or other error, continue
                continue
        
        # logger.info(f"Worker {agent_type} stopped")
    
    def _process_task(self, task: AgentTask):
        """Process a single task"""
        try:
            task.status = 'running'
            task.completed_at = None
            self._update_task(task)
            
            # Get the appropriate agent
            agent = self.agents.get(task.agent_type)
            if not agent:
                raise ValueError(f"Unknown agent type: {task.agent_type}")
            
            # Process the task based on agent type
            # Use the agent_input directly from the task
            agent_input = task.agent_input
            
            if task.agent_type == 'builder':
                result = agent.build_argument(agent_input)
            elif task.agent_type == 'content_evaluator':
                # Create FilteredAgentInput for content evaluation
                filtered_input = FilteredAgentInput.for_content_evaluation(agent_input)
                result = agent.evaluate_propositions(filtered_input)
            elif task.agent_type == 'form_evaluator':
                # Create FilteredAgentInput for form evaluation
                filtered_input = FilteredAgentInput.for_formal_evaluation(agent_input)
                result = agent.evaluate_propositions(filtered_input)
            elif task.agent_type == 'formalizer':
                # Create FilteredAgentInput for formalization
                filtered_input = FilteredAgentInput.for_formalization(agent_input)
                result = agent.formalize_proposition(filtered_input)
            elif task.agent_type == 'rewriter':
                result = agent.rewrite_proposition(agent_input)
            elif task.agent_type == 'improver':
                result = agent.generate_improvements(agent_input)
            else:
                raise ValueError(f"Unknown agent type: {task.agent_type}")
            
            # Set snapshot_id on the agent result
            result.snapshot_id = agent_input.snapshot_id
            
            # Create stored agent result
            target_metadata = TargetMetadata(
                target_type=agent_input.agent_data.target_type,
                target_content=agent_input.agent_data.target_content or ''
            )
            stored_result = StoredAgentResult(
                agent_type=result.agent_type,
                operation=result.operation,
                result_content=result.result_content,
                confidence=result.confidence,
                reasoning=result.reasoning,
                target_metadata=target_metadata,
                snapshot_id=result.snapshot_id,
                processed_at=time.time()
            )
            
            # Store result using the disciplined result manager
            self.result_manager.add_result(task.agent_input.conversation_id, stored_result)
            
            # Keep task.result as dict for backward compatibility with task history
            task.result = {
                'agent_type': result.agent_type,
                'operation': result.operation,
                'result_content': result.result_content,
                'confidence': result.confidence,
                'reasoning': result.reasoning,
                'target_metadata': result.target_metadata,
                'snapshot_id': result.snapshot_id,
                'processed_at': time.time()
            }
            
            # Check if improvement agent should be triggered after this agent completes
            if result.agent_type in ['content_evaluator', 'form_evaluator']:
                # Create argument data for improvement agent check
                argument_data = ArgumentData(
                    argument=task.agent_input.agent_data.argument,
                    assumptions=task.agent_input.agent_data.assumptions,
                    file_ids=task.agent_input.file_ids
                )
                
                # Queue improvement agent if ready
                self.queue_improvement_agent_if_ready(
                    task.agent_input.conversation_id,
                    task.agent_input.snapshot_id,
                    argument_data
                )
                        
            # Debug logging
            # logger.info(f"Stored result for {task.agent_type} agent in conversation {task.conversation_id}")
            # logger.debug(f"Current results for conversation {task.conversation_id}: {self.result_manager.get_results(task.conversation_id)}")
            
            task.status = 'completed'
            task.completed_at = time.time()
            
        except Exception as e:
            task.status = 'failed'
            task.error = str(e)
            task.completed_at = time.time()
            logger.error(f"Task {task.id} failed: {e}")
        
        finally:
            self._update_task(task)
    
    def _update_task(self, task: AgentTask):
        """Update task in history"""
        self.task_history[task.id] = task
    
    def _get_next_task_for_agent(self, agent_type: str) -> Optional[AgentTask]:
        """Get next task for specific agent type with snapshot-based prioritization"""
        with self.task_queue_lock:
            if not self.task_queue:
                return None
            
            # Try to find a task for the most recent conversation/snapshot first
            if self.most_recent_conversation and self.most_recent_snapshot:
                for task in self.task_queue:
                    is_most_recent = (task.agent_type == agent_type and
                        task.agent_input.conversation_id == self.most_recent_conversation and
                        int(task.agent_input.snapshot_id) == self.most_recent_snapshot)
                    if is_most_recent:
                        self.task_queue.remove(task)
                        return task
            
            # Otherwise return any task of the right type
            for task in self.task_queue:
                if task.agent_type == agent_type:
                    self.task_queue.remove(task)
                    return task
            
            return None
    
    def queue_task(self, agent_type: str, agent_input: AgentInput, priority: int = 0) -> str:
        """Queue a new task for processing"""
        task_id = str(uuid.uuid4())
        
        task = AgentTask(
            id=task_id,
            agent_type=agent_type,
            agent_input=agent_input,
            priority=priority
        )
        
        with self.task_queue_lock:
            self.task_queue.append(task)
        self.task_history[task_id] = task
        
        # logger.info(f"Queued task {task_id} for {agent_type} agent in conversation {agent_input.conversation_id}")
        return task_id
    
    def get_task_status(self, task_id: str) -> Optional[AgentTask]:
        """Get the status of a specific task"""
        return self.task_history.get(task_id)
    
    def get_conversation_results(self, conversation_id: str) -> List[StoredAgentResult]:
        """Get all results for a conversation"""
        results = self.result_manager.get_results(conversation_id)
        # logger.debug(f"Retrieved {len(results)} results for conversation {conversation_id}")
        # logger.debug(f"Results: {results}")
        return results
    
    def get_latest_results(self, conversation_id: str, snapshot_id: str) -> List[StoredAgentResult]:
        """Get latest results for a conversation/snapshot context"""
        # Update most recent conversation/snapshot for prioritization
        self.most_recent_conversation = conversation_id
        self.most_recent_snapshot = int(snapshot_id)
        
        return self.result_manager.get_latest_results(conversation_id, snapshot_id)
    

    
    def get_results_by_target_type(self, conversation_id: str, target_type: str, snapshot_id: str) -> List[StoredAgentResult]:
        """Get results filtered by target type (argument vs proposition level)"""
        return self.result_manager.get_results_by_target_type(conversation_id, target_type, snapshot_id)
    
    def create_agent_input(self, conversation_id: str, snapshot_id: str, agent_data: AgentData, 
                          file_ids: List[str] = None, triggered_by: str = 'system', 
                          trigger_source: str = 'result_propagation') -> AgentInput:
        """Create agent input with latest results context"""
        # Get latest results for context
        latest_results = self.get_latest_results(conversation_id, snapshot_id)
        
        # Convert StoredAgentResult objects to dict format for AgentData
        results_dicts = [result.model_dump() for result in latest_results]
        
        # Update agent_data with latest results
        agent_data.latest_results = results_dicts
        
        return AgentInput(
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
            agent_data=agent_data,
            file_ids=file_ids or [],
            triggered_by=triggered_by,
            trigger_source=trigger_source
        )
    
    def create_improvement_agent_input(self, conversation_id: str, snapshot_id: str, argument_data: ArgumentData,
                                     file_ids: List[str] = None) -> AgentInput:
        """Create specialized input for improvement agent with evaluation results and conclusion context"""
        # Get all results for this conversation/snapshot
        all_results = self.get_conversation_results(conversation_id)
        snapshot_results = [r for r in all_results if r.snapshot_id == snapshot_id]
        
        # Extract all evaluation results together (no need to separate by type initially)
        evaluation_results = [
            result.model_dump() 
            for result in snapshot_results 
            if result.agent_type in ['content_evaluator', 'form_evaluator']
        ]
                
        # Create agent data with evaluation results in latest_results
        agent_data = AgentData(
            assumptions=argument_data.assumptions,
            argument=argument_data.argument,
            latest_results=evaluation_results,  # All evaluation results together
            target_type='argument',
            target_content=None
        )
        
        # Create the input with evaluation results
        agent_input = AgentInput(
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
            agent_data=agent_data,
            file_ids=file_ids or [],
            triggered_by='agent_cascade',
            trigger_source='evaluation_complete'
        )
                
        return agent_input
    
    def create_agent_result(self, agent_type: str, operation: str, result_content: Dict[str, Any],
                           confidence: float, reasoning: str, target_metadata: TargetMetadata,
                           snapshot_id: str) -> StoredAgentResult:
        """Create properly structured agent result"""
        return StoredAgentResult(
            agent_type=agent_type,
            operation=operation,
            result_content=result_content,
            confidence=confidence,
            reasoning=reasoning,
            target_metadata=target_metadata,
            snapshot_id=snapshot_id,
            processed_at=time.time()
        )
    
    def are_conversation_tasks_complete(self, conversation_id: str, snapshot_id: str = None) -> bool:
        """Check if all tasks for a conversation/snapshot are complete"""
        # Get all tasks for this conversation from history
        conversation_tasks = [
            task for task in self.task_history.values() 
            if task.agent_input.conversation_id == conversation_id
        ]
        
        # If snapshot_id is provided, filter by snapshot_id as well
        if snapshot_id is not None:
            conversation_tasks = [
                task for task in conversation_tasks
                if task.agent_input.snapshot_id == snapshot_id
            ]
        
        if not conversation_tasks:
            return True  # No tasks means complete
        
        # Check if all tasks are completed or failed
        return all(task.status in ['completed', 'failed'] for task in conversation_tasks)
    
    def get_active_tasks(self) -> list:
        """Get all active tasks"""
        return [task for task in self.task_history.values() 
                if task.status in ['pending', 'running']]
    
    def react_to_user_argument_change(self, conversation_id: str, snapshot_id: str, argument_data: ArgumentData):
        """
        Reactively queue agents based on user-initiated argument changes.
        This method analyzes the current argument state and queues necessary agents
        to keep results in sync with the new argument state after user modifications.
        """

        # Extract all propositions from the argument
        all_propositions = []
        argument_propositions = [step.proposition for step in argument_data.argument]
        assumption_propositions = [step.proposition for step in argument_data.assumptions]
        
        all_propositions.extend(argument_propositions)
        all_propositions.extend(assumption_propositions)
        
        # Get existing results to understand current state
        existing_results = self.get_conversation_results(conversation_id)
        
        # Queue builder agent for content discovery
        builder_agent_input = AgentInput(
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
            agent_data=AgentData(
                assumptions=argument_data.assumptions,
                argument=argument_data.argument,
                latest_results=[],
                target_type='argument',
                target_content=None
            ),
            file_ids=argument_data.file_ids,
            triggered_by='user_action',
            trigger_source='argument_change'
        )
        self.queue_task(
            agent_type='builder',
            agent_input=builder_agent_input
        )
        
        # Queue formalizer for the entire argument
        # Check if we need to formalize any steps
        needs_formalization = False
        for step in argument_data.argument + argument_data.assumptions:
            if not step.formalization or not step.formalization.endorsed:
                needs_formalization = True
                break
        
        if needs_formalization:
            # logger.info(f"Queueing formalizer task for argument in conversation {conversation_id}")
            formalizer_agent_input = AgentInput(
                conversation_id=conversation_id,
                snapshot_id=snapshot_id,
                agent_data=AgentData(
                    assumptions=argument_data.assumptions,
                    argument=argument_data.argument,
                    latest_results=[],
                    target_type='argument',
                    target_content=None
                ),
                file_ids=argument_data.file_ids,
                triggered_by='user_action',
                trigger_source='argument_change'
            )
            # logger.debug(f"Queueing formalizer task for argument")
            self.queue_task(
                agent_type='formalizer',
                agent_input=formalizer_agent_input
            )
        else:
            # logger.info(f"No formalization needed for conversation {conversation_id}")
            pass
        
        # Queue content evaluator for argument analysis
        content_evaluator_agent_input = AgentInput(
            conversation_id=conversation_id,
            snapshot_id=snapshot_id,
            agent_data=AgentData(
                assumptions=argument_data.assumptions,
                argument=argument_data.argument,
                latest_results=[],
                target_type='argument',
                target_content=None
            ),
            file_ids=argument_data.file_ids,
            triggered_by='user_action',
            trigger_source='argument_change'
        )
        self.queue_task(
            agent_type='content_evaluator',
            agent_input=content_evaluator_agent_input
        )
        
        # logger.info(f"Reactively queued agents for argument state change in conversation {conversation_id}")

        self.queue_formal_evaluator_if_ready(conversation_id, snapshot_id, argument_data)

    
    def queue_improvement_agent_if_ready(self, conversation_id: str, snapshot_id: str, argument_data: ArgumentData):
        """
        Queue an improvement agent task if evaluation results are available and improvement agent hasn't run recently.
        This function checks if the improvement agent should be triggered based on evaluation results.
        """
        # logger.debug(f"Queueing improvement agent if ready for conversation {conversation_id}")
        logger.debug(f"Queueing improvement agent if ready for conversation {conversation_id}")

        # Check if there's already a pending or running improvement agent task
        active_tasks = self.get_active_tasks()
        for task in active_tasks:
            if task.agent_type == 'improver' and task.agent_input.conversation_id == conversation_id and task.agent_input.snapshot_id == snapshot_id:
                logger.info(f"Improvement agent task already active for conversation {conversation_id}")
                return
        
        # Check if improvement agent should be triggered
        should_trigger = self._should_queue_improvement_agent(conversation_id, snapshot_id, argument_data)
        
        if should_trigger:
            # Queue improvement agent task using specialized input creation
            improvement_agent_input = self.create_improvement_agent_input(
                conversation_id, snapshot_id, argument_data, argument_data.file_ids
            )
            
            self.queue_task(
                agent_type='improver',
                agent_input=improvement_agent_input
            )
            logger.info(f"Queued improvement agent task for conversation {conversation_id}")
        else:
            logger.debug(f"Improvement agent not ready for conversation {conversation_id}")
    
    def _should_queue_improvement_agent(self, conversation_id: str, snapshot_id: str, argument_data: ArgumentData) -> bool:
        """
        Determine if the improvement agent should be queued based on evaluation results and formalization status.
        Returns True if improvement agent should run, False otherwise.
        """
        # Get existing results to understand current state
        existing_results = self.get_conversation_results(conversation_id)
        
        # Check if content evaluation results are available
        content_evaluation_results = [
            result for result in existing_results 
            if result.get('agent_type') == 'content_evaluator' and 
               result.get('snapshot_id') == snapshot_id
        ]
        
        # Check if formal evaluation results are available
        formal_evaluation_results = [
            result for result in existing_results 
            if result.get('agent_type') == 'form_evaluator' and 
               result.get('snapshot_id') == snapshot_id
        ]
        
        # Check if all propositions have endorsed formalizations
        all_propositions_formalized = True
        for step in argument_data.argument + argument_data.assumptions:
            if not step.formalization or not step.formalization.endorsed:
                all_propositions_formalized = False
                break
        
        # Check if improvement agent has already run for this snapshot
        improvement_results = [
            result for result in existing_results 
            if result.get('agent_type') == 'improver' and 
               result.get('snapshot_id') == snapshot_id
        ]
        
        # Determine trigger conditions based on design document
        if content_evaluation_results and not all_propositions_formalized:
            # Content evaluation trigger: when content evaluation results are available AND not all propositions have endorsed formalizations
            logger.debug(f"Content evaluation trigger for improvement agent in conversation {conversation_id}")
            return not improvement_results  # Only trigger if improvement agent hasn't run yet
            
        elif formal_evaluation_results and all_propositions_formalized:
            # Formal evaluation trigger: when formal evaluation results are available AND all propositions have endorsed formalizations
            logger.debug(f"Formal evaluation trigger for improvement agent in conversation {conversation_id}")
            return not improvement_results  # Only trigger if improvement agent hasn't run yet
        
        return False
    
    def queue_formal_evaluator_if_ready(self, conversation_id: str, snapshot_id: str, argument_data: ArgumentData):
        """
        Queue a formal_evaluator task if all formalizations are in place and existing formal_evaluator is outdated.
        Checks that no formal_evaluator is already 'pending' or 'running'.
        """
        # logger.debug(f"Queueing formal evaluator if ready for conversation {conversation_id}")
        logger.debug(f"Queueing formal evaluator if ready for conversation {conversation_id}")

        # Check if there's already a pending or running formal_evaluator task
        active_tasks = self.get_active_tasks()
        for task in active_tasks:
            if task.agent_type == 'form_evaluator' and task.agent_input.conversation_id == conversation_id and task.agent_input.snapshot_id == snapshot_id:
                logger.info(f"Form evaluator task already active for conversation {conversation_id}")
                return
        
        logger.debug(f"Checking if formal evaluator is ready for conversation {conversation_id}")
        # Extract proposition texts from the argument for form evaluator check
        form_eval_argument_propositions = []
        
        # Extract propositions from list[Step] format
        argument_steps = argument_data.argument
        
        for step in argument_steps:
            proposition = step.proposition
            if proposition:
                form_eval_argument_propositions.append(proposition)

        logger.debug(f"Form evaluator argument propositions: {form_eval_argument_propositions}")

        # Check if all propositions in the argument AND assumptions have endorsed formalizations
        # The formal evaluator now gets formalizations directly from Step objects
        all_propositions_formalized = True
        
        # Check argument steps
        for step in argument_steps:
            proposition = step.proposition
            formalization = step.formalization
            if proposition and (not formalization or not formalization.endorsed):
                all_propositions_formalized = False
                break
        
        # Check assumption steps if argument steps are all formalized
        if all_propositions_formalized:
            assumption_steps = argument_data.assumptions
            for step in assumption_steps:
                proposition = step.proposition
                formalization = step.formalization
                if proposition and (not formalization or not formalization.endorsed):
                    all_propositions_formalized = False
                    break
        
        logger.debug(f"All propositions formalized: {all_propositions_formalized}")
        
        if all_propositions_formalized:
            # Queue form evaluator task
            form_evaluator_agent_input = AgentInput(
                conversation_id=conversation_id,
                snapshot_id=snapshot_id,
                agent_data=AgentData(
                    assumptions=argument_data.assumptions,
                    argument=argument_data.argument,
                    latest_results=[],
                    target_type='argument',
                    target_content=None
                ),
                file_ids=argument_data.file_ids,
                triggered_by='user_action',
                trigger_source='formalization_complete'
            )
            
            self.queue_task(
                agent_type='form_evaluator',
                agent_input=form_evaluator_agent_input
            )
            logger.info(f"Queued form evaluator task for conversation {conversation_id}")
        else:
            logger.info(f"Not all propositions formalized yet for conversation {conversation_id}")
    
    def stop(self):
        """Stop all workers"""
        self.running = False
        logger.info("AgentCoordinator stopping all workers")
    

# Global coordinator instance
coordinator = AgentCoordinator() 
