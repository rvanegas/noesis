# Agent Results by Snapshot Implementation Plan

## Overview

This document outlines the implementation plan for storing agent results by snapshot on both backend and frontend, with hierarchical organization by `conversation_id`, `snapshot_id`, and `agent_type`. The system will prioritize tasks by snapshot_id (most recent first) and always display the most recent snapshot results for a given conversation and agent type.

## Current State Analysis

### Existing Architecture
- **Agent Results**: Stored by `conversation_id` only
- **Task Queue**: FIFO (first-in, first-out) processing
- **Frontend Display**: Shows results by conversation only
- **No Snapshot Association**: Results not tied to specific snapshots
- **No Prioritization**: All tasks processed in order received

### Problems Addressed
1. **No Snapshot Context**: Agent results not associated with specific conversation snapshots
2. **Poor Prioritization**: Old snapshots processed before recent ones
3. **Limited Historical Access**: Can't access results from previous snapshots
4. **Inefficient State Management**: No clear hierarchy for result organization

## Implementation Plan

### 1. Backend Changes

#### **Current State Analysis**

**Existing AgentResultManager** - Already Complete ✅:
- ✅ **Data Structures** - `AgentResult` already has `snapshot_id` field
- ✅ **Storage** - `add_result()` already stores by snapshot
- ✅ **Retrieval** - `get_latest_results()` already provides snapshot-based filtering
- ✅ **API** - Existing endpoints already work with snapshot context

**Existing Frontend** - Already Complete ✅:
- ✅ **Store** - Already has snapshot-based state management
- ✅ **Components** - Already access current snapshot context
- ✅ **Result Application** - Already applies results to current snapshot

#### **Only Change Needed: Task Queue Prioritization**

The **only modification** required is in the task queue to prioritize by current snapshot:

```python
class AgentCoordinator:
    def __init__(self):
        # ... existing initialization ...
        self.current_snapshot_by_conversation: Dict[str, int] = {}  # Track current snapshot per conversation
    
    def update_current_snapshot(self, conversation_id: str, snapshot_id: str):
        """Update the current snapshot for a conversation (called by get_latest_results)"""
        self.current_snapshot_by_conversation[conversation_id] = int(snapshot_id)
    
    def get_next_task(self) -> Task:
        """Get next task, prioritizing by current snapshot"""
        if not self.task_queue:
            return None
            
        # Find tasks for the most recent current snapshot
        max_current_snapshot = max(self.current_snapshot_by_conversation.values()) if self.current_snapshot_by_conversation else 0
        
        # Filter tasks by current snapshot priority
        current_snapshot_tasks = [
            task for task in self.task_queue
            if task.agent_input.conversation_id in self.current_snapshot_by_conversation and
               int(task.agent_input.snapshot_id) == self.current_snapshot_by_conversation[task.agent_input.conversation_id]
        ]
        
        # If we have current snapshot tasks, return the first one
        if current_snapshot_tasks:
            task = current_snapshot_tasks[0]
            self.task_queue.remove(task)
            return task
        
        # Otherwise, return the first task in the queue (FIFO for older snapshots)
        return self.task_queue.pop(0) if self.task_queue else None
```

### 2. Frontend Changes

#### **No Changes Required** ✅

The frontend already has all the functionality needed:
- ✅ **Store** - Already has snapshot-based state management
- ✅ **Components** - Already access current snapshot context via `getCurrentSnapshotId()`
- ✅ **Result Application** - Already applies results to current snapshot
- ✅ **API Calls** - Already pass snapshot context to backend

The existing frontend implementation already works perfectly with the snapshot-based prioritization.

### 3. API Changes

#### **No Changes Required** ✅

The existing API endpoints already work perfectly:
- ✅ **`/agent-results/{conversation_id}`** - Already returns latest results
- ✅ **`/agent-results/{conversation_id}/{snapshot_id}`** - Already returns snapshot-specific results
- ✅ **All existing endpoints** - Already support snapshot context

The API already provides all the functionality needed for snapshot-based agent results.

### 4. Benefits of This Approach

#### **Snapshot Association** ✅
- Results tied to specific conversation snapshots
- Historical context preserved
- Clear relationship between argument state and agent results

#### **Temporal Prioritization** ✅
- Most recent snapshots processed first
- Prevents old work from blocking new work
- Responsive to user activity

#### **Clean State Management** ✅
- Hierarchical organization: conversation → snapshot → agent type
- Efficient retrieval patterns
- Clear data flow

#### **Performance** ✅
- Fast access to latest results
- Efficient storage and retrieval
- Minimal memory footprint

#### **Scalability** ✅
- Hierarchical structure supports growth
- Easy to add new agent types
- TTL support for cleanup

#### **User Experience** ✅
- Always see most recent results
- Historical access when needed
- Responsive to user actions

### 5. Implementation Order

#### **Phase 1: Task Queue Prioritization (1 day)**
1. **AgentCoordinator** - Add current snapshot tracking
2. **get_latest_results** - Update to notify coordinator of current snapshot
3. **get_next_task** - Modify to prioritize current snapshot tasks
4. **Testing** - Verify prioritization works correctly

#### **Phase 2: Verification (1 day)**
1. **Integration Testing** - Ensure existing functionality still works
2. **Performance Testing** - Verify prioritization improves responsiveness
3. **User Testing** - Validate improved user experience

### 6. Migration Strategy

#### **No Migration Required** ✅
- **Zero Breaking Changes** - All existing functionality continues to work
- **No Data Migration** - Existing data structures remain unchanged
- **No API Changes** - All existing endpoints continue to work
- **No Frontend Changes** - Current frontend already works with snapshot context

#### **Rollout Plan**
1. **Deploy Backend Change** - Single modification to task queue prioritization
2. **Verify Functionality** - Ensure existing features still work
3. **Monitor Performance** - Verify prioritization improves responsiveness

### 7. Success Metrics

#### **Technical Metrics**
- **Response Time**: Agent result retrieval < 100ms
- **Storage Efficiency**: < 20% increase in storage usage
- **Queue Performance**: Priority tasks processed within 5 seconds
- **Memory Usage**: < 10% increase in frontend memory usage

#### **User Experience Metrics**
- **Responsiveness**: 50% improvement in result update speed
- **Context Awareness**: Users can access historical results
- **Task Prioritization**: Recent work prioritized over old work
- **Data Consistency**: Results always match current snapshot state

## Conclusion

This implementation plan provides a robust foundation for snapshot-based agent result management, addressing the key requirements from the rearchitecture plan:

1. **Snapshot Association** - Results tied to specific conversation snapshots
2. **Temporal Prioritization** - Most recent snapshots processed first
3. **Historical Context** - Access to results from previous snapshots
4. **Clean State Management** - Hierarchical organization in both frontend and backend
5. **Performance** - Efficient retrieval and storage patterns
6. **Scalability** - Structure supports future growth and new agent types

The phased implementation ensures minimal disruption while delivering significant improvements in functionality, performance, and user experience.
