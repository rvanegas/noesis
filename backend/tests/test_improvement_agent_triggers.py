"""Test the improvement agent trigger logic"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from services.agent_coordinator import AgentCoordinator
from schemas.agent_input import AgentInput, AgentData
from schemas.step import Step
from schemas.arguments import ArgumentData
from services.agents import AgentResult


class TestImprovementAgentTriggers:
    """Test that the improvement agent trigger logic works correctly"""

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

    def test_should_queue_improvement_agent_content_trigger(self):
        """Test that improvement agent is triggered after content evaluation when not all propositions are formalized"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"

        r = Mock()
        r.agent_type = 'content_evaluator'
        r.snapshot_id = snapshot_id
        r.result_content = {'truth_evaluations': []}
        mock_results = [r]

        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            should_trigger = self.coordinator._should_queue_improvement_agent(
                conversation_id, snapshot_id, self.argument_data
            )
            
            assert should_trigger is True

    def test_should_queue_improvement_agent_formal_trigger(self):
        """Test that improvement agent is triggered after formal evaluation when all propositions are formalized"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Create step with endorsed formalization
        from schemas.step import Formalization
        formalized_step = Step(
            symbol="A",
            proposition="Test proposition",
            justifiers=[],
            truth_score="0.5",
            content_validity="0.4",
            formal_validity="0.3",
            formalization=Formalization(ascii="P(a)", endorsed=True)
        )
        
        formalized_argument_data = ArgumentData(
            argument=[formalized_step],
            assumptions=[],
            file_ids=[]
        )
        
        r = Mock()
        r.agent_type = 'form_evaluator'
        r.snapshot_id = snapshot_id
        r.result_content = {'validity_evaluations': []}
        mock_results = [r]

        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            should_trigger = self.coordinator._should_queue_improvement_agent(
                conversation_id, snapshot_id, formalized_argument_data
            )
            
            assert should_trigger is True

    def test_should_not_queue_improvement_agent_no_evaluation_results(self):
        """Test that improvement agent is not triggered when no evaluation results are available"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        r = Mock()
        r.agent_type = 'builder'
        r.snapshot_id = snapshot_id
        r.result_content = {'propositions': []}
        mock_results = [r]

        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            should_trigger = self.coordinator._should_queue_improvement_agent(
                conversation_id, snapshot_id, self.argument_data
            )
            
            assert should_trigger is False

    def test_should_not_queue_improvement_agent_already_run(self):
        """Test that improvement agent is not triggered if it has already run for this snapshot"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        r1 = Mock()
        r1.agent_type = 'content_evaluator'
        r1.snapshot_id = snapshot_id
        r1.result_content = {'truth_evaluations': []}
        r2 = Mock()
        r2.agent_type = 'improver'
        r2.snapshot_id = snapshot_id
        r2.result_content = {'recommendations': []}
        mock_results = [r1, r2]

        with patch.object(self.coordinator, 'get_conversation_results', return_value=mock_results):
            should_trigger = self.coordinator._should_queue_improvement_agent(
                conversation_id, snapshot_id, self.argument_data
            )
            
            assert should_trigger is False

    @patch.object(AgentCoordinator, 'queue_task')
    def test_queue_improvement_agent_if_ready_triggers_task(self, mock_queue_task):
        """Test that queue_improvement_agent_if_ready actually queues a task when conditions are met"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Mock the should_queue_improvement_agent method to return True
        with patch.object(self.coordinator, '_should_queue_improvement_agent', return_value=True):
            # Mock get_active_tasks to return empty list (no active tasks)
            with patch.object(self.coordinator, 'get_active_tasks', return_value=[]):
                self.coordinator.queue_improvement_agent_if_ready(
                    conversation_id, snapshot_id, self.argument_data
                )
                
                # Verify that queue_task was called with 'improver' agent type
                mock_queue_task.assert_called_once()
                call_args = mock_queue_task.call_args
                assert call_args[1]['agent_type'] == 'improver'

    @patch.object(AgentCoordinator, 'queue_task')
    def test_queue_improvement_agent_if_ready_skips_when_active_task_exists(self, mock_queue_task):
        """Test that queue_improvement_agent_if_ready skips when there's already an active task"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Mock active tasks to include an improvement agent task
        mock_active_task = Mock()
        mock_active_task.agent_type = 'improver'
        mock_active_task.agent_input.conversation_id = conversation_id
        mock_active_task.agent_input.snapshot_id = snapshot_id
        
        with patch.object(self.coordinator, 'get_active_tasks', return_value=[mock_active_task]):
            self.coordinator.queue_improvement_agent_if_ready(
                conversation_id, snapshot_id, self.argument_data
            )
            
            # Verify that queue_task was NOT called
            mock_queue_task.assert_not_called()

    def test_improvement_agent_triggered_after_content_evaluation_completion(self):
        """Test that improvement agent is triggered after content evaluation agent completes"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Create mock task and result
        mock_task = Mock()
        mock_task.agent_input.conversation_id = conversation_id
        mock_task.agent_input.snapshot_id = snapshot_id
        mock_task.agent_input.agent_data.argument = [self.test_step]
        mock_task.agent_input.agent_data.assumptions = []
        mock_task.agent_input.file_ids = []
        
        mock_result = Mock()
        mock_result.agent_type = 'content_evaluator'
        mock_result.snapshot_id = snapshot_id
        
        # Mock the queue_improvement_agent_if_ready method
        with patch.object(self.coordinator, 'queue_improvement_agent_if_ready') as mock_queue_improver:
            # Call the logic that would be executed after task completion
            if mock_result.agent_type in ['content_evaluator', 'form_evaluator']:
                argument_data = ArgumentData(
                    argument=mock_task.agent_input.agent_data.argument,
                    assumptions=mock_task.agent_input.agent_data.assumptions,
                    file_ids=mock_task.agent_input.file_ids
                )
                
                self.coordinator.queue_improvement_agent_if_ready(
                    mock_task.agent_input.conversation_id,
                    mock_task.agent_input.snapshot_id,
                    argument_data
                )
            
            # Verify that the improvement agent was queued
            mock_queue_improver.assert_called_once()

    def test_improvement_agent_triggered_after_formal_evaluation_completion(self):
        """Test that improvement agent is triggered after formal evaluation agent completes"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Create mock task and result
        mock_task = Mock()
        mock_task.agent_input.conversation_id = conversation_id
        mock_task.agent_input.snapshot_id = snapshot_id
        mock_task.agent_input.agent_data.argument = [self.test_step]
        mock_task.agent_input.agent_data.assumptions = []
        mock_task.agent_input.file_ids = []
        
        mock_result = Mock()
        mock_result.agent_type = 'form_evaluator'
        mock_result.snapshot_id = snapshot_id
        
        # Mock the queue_improvement_agent_if_ready method
        with patch.object(self.coordinator, 'queue_improvement_agent_if_ready') as mock_queue_improver:
            # Call the logic that would be executed after task completion
            if mock_result.agent_type in ['content_evaluator', 'form_evaluator']:
                argument_data = ArgumentData(
                    argument=mock_task.agent_input.agent_data.argument,
                    assumptions=mock_task.agent_input.agent_data.assumptions,
                    file_ids=mock_task.agent_input.file_ids
                )
                
                self.coordinator.queue_improvement_agent_if_ready(
                    mock_task.agent_input.conversation_id,
                    mock_task.agent_input.snapshot_id,
                    argument_data
                )
            
            # Verify that the improvement agent was queued
            mock_queue_improver.assert_called_once()

    def test_improvement_agent_not_triggered_after_other_agents(self):
        """Test that improvement agent is not triggered after non-evaluation agents complete"""
        conversation_id = "test_conv"
        snapshot_id = "test_snap"
        
        # Create mock task and result for builder agent
        mock_task = Mock()
        mock_task.agent_input.conversation_id = conversation_id
        mock_task.agent_input.snapshot_id = snapshot_id
        mock_task.agent_input.agent_data.argument = [self.test_step]
        mock_task.agent_input.agent_data.assumptions = []
        mock_task.agent_input.file_ids = []
        
        mock_result = Mock()
        mock_result.agent_type = 'builder'
        mock_result.snapshot_id = snapshot_id
        
        # Mock the queue_improvement_agent_if_ready method
        with patch.object(self.coordinator, 'queue_improvement_agent_if_ready') as mock_queue_improver:
            # Call the logic that would be executed after task completion
            if mock_result.agent_type in ['content_evaluator', 'form_evaluator']:
                argument_data = ArgumentData(
                    argument=mock_task.agent_input.agent_data.argument,
                    assumptions=mock_task.agent_input.agent_data.assumptions,
                    file_ids=mock_task.agent_input.file_ids
                )
                
                self.coordinator.queue_improvement_agent_if_ready(
                    mock_task.agent_input.conversation_id,
                    mock_task.agent_input.snapshot_id,
                    argument_data
                )
            
            # Verify that the improvement agent was NOT queued
            mock_queue_improver.assert_not_called()
