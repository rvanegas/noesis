# Agent Rearchitecture Plan

## Overview

This document outlines a comprehensive rearchitecture of the agent system in Dianoia, addressing seven key areas:

1. **Input Normalization** - Standardize how agents receive and process input
2. **Agent Type Reorganization** - Restructure agent functions into a new array of agent types
3. **Trigger Mechanism Rearchitecture** - Redesign how agents are triggered and coordinated
4. **Snapshot Association** - Associate agents with conversation snapshots, not just conversations
5. **TTL Implementation** - Introduce time-to-live mechanisms on agent results
6. **Frontend Integration** - Propagate changes to the frontend accordingly
7. **Frontend State Management** - Centralize frontend state management using Zustand

## Current State Analysis

### Existing Architecture
- **Agent Types**: `builder`, `content_evaluator`, `form_evaluator`, `formalizer`, `rewriter`
- **Coordination**: Backend-driven with `AgentCoordinator` managing task queues
- **Triggering**: Reactive to argument state changes via `react_to_user_argument_change()`
- **Association**: Agents tied to `conversation_id` only
- **Results**: Stored in `AgentResultManager` with basic cleanup
- **Frontend**: `AllAgentResults` component displays results by conversation

### Critical Architectural Gap: Loop Closure
**Problem**: The system has a fundamental disconnect between data sources and agent dependencies:

1. **Frontend is source of truth for argument data** - Users edit arguments in the frontend
2. **Backend is source of truth for agent results** - Agents produce results stored in backend
3. **Later agents depend on earlier agent results** - Formal evaluator needs formalization results, improvement agent needs content evaluation results
4. **Loop closure happens through argument data** - Frontend copies agent results into argument steps, then serializes to backend

**Current Flow**:
- **Agents produce results** → **Frontend copies into argument steps** → **Frontend serializes to backend** → **Backend processes updated argument**

**Specific Issues**:
- **Content Evaluator → Improvement Agent**: Improvement agent can't access content evaluation results (truth/validity values)
- **Formalizer → Formal Evaluator**: Formal evaluator can't access formalization results (formalization strings)
- **Formalizer → User Review**: Users can't review/accept/reject formalizations before they're embedded in argument
- **Agent Results → Argument Steps**: Frontend copies agent results into argument steps, but this is manual and not systematic

### Current Issues
1. **Input Inconsistency**: Different agents receive data in different formats
2. **Agent Overlap**: Some agents have overlapping responsibilities
3. **Rigid Triggering**: Agents only trigger on specific argument changes
4. **No Snapshot Awareness**: Agents don't understand conversation history/context
5. **No Result Expiration**: Results persist indefinitely
6. **Limited Frontend Integration**: Basic result display without rich interaction
7. **❌ CRITICAL: No Loop Closure**: Agent results not available to dependent agents or users

## 1. Input Normalization

### Problem
Agents currently receive data in inconsistent formats:
- `builder` receives `argument_data` with nested structure
- `content_evaluator` receives flat `argument` and `assumptions` lists
- `formalizer` receives individual `proposition` strings
- No standardized context or metadata

### Solution: Normalized Agent Input Schema

```typescript
interface AgentInput {
  // Core identification
  conversation_id: string
  snapshot_id: string
  
  // Context data
  context: {
    assumptions: Step[]
    argument: Step[]
    file_ids: string[]
    user_preferences: UserPreferences
  }
  
  // Note: Step model must be updated to include formalization and separate validity attributes
  // Step = {
  //   symbol: string
  //   proposition: string
  //   justifiers: string[]
  //   truth: string
  //   valid_content: string    // Validity from content evaluation
  //   valid_formal: string     // Validity from formal evaluation
  //   formalization?: string   // Formal logic representation
  // }
  
  // Task-specific data
  task_data: {
    target_type: 'argument' | 'proposition'
    target_content: string  // proposition text if target_type is 'proposition', undefined if 'argument'
  }
  
  // Metadata
  metadata: {
    triggered_by: 'user_action' | 'agent_cascade' | 'scheduled' | 'manual'
    trigger_source: string
    timestamp: number
    ttl_seconds: number
  }
}
```

### Implementation
- Update Step model to include formalization attribute
- Implement agent input filtering (formalization omitted for content evaluation, content omitted for formal evaluation)
- Standardize all agent entry points
- Add validation and transformation logic

## 2. Agent Type Reorganization

### Problem
Current agents have overlapping responsibilities and unclear boundaries:
- `builder` and `rewriter` both modify propositions
- `content_evaluator` and `form_evaluator` both evaluate
- No clear specialization or hierarchy

### Required Agent Functions
Based on analysis of argumentation needs, agents must perform these specific functions:

1. **Evaluate truth of propositions**
   - Only those which were not evaluated in previous snapshot

2. **Evaluate validity of inferences**
   - Only those inferences which were not evaluated in previous snapshot
   - An inference from P, Q to R is equivalent to the evaluation of the truth of "if P and Q then R" where the conditional is strict implication, not material implication

3. **Check coherence**
   - Flag sets of incoherent propositions
   - That a set of propositions P, Q is incoherent is equivalent to the truth of "if P and Q then False" where the conditional is strict implication, not material implication

4. **Identify weakest inferences in argument**
   - Inferences whose validity, that is whose corresponding strict implication conditional are not absolutely true, are weakly valid

5. **Identify missing premises**
   - The additional premise with which a weakly valid inference would be stronger is a missing premise

6. **Recommend proposition rewriting and step reordering**
   - Recommend individual propositions rewrites
   - Recommend separating composite propositions into multiple simple propositions to make inferences explicit
   - Recommend combining simple propositions into composites for clarity
   - Recommend rewrites that serve formalization

7. **Formalize argument**
   - Select logical complexity: propositional, predicates, quantifiers, modes
   - Select predicates and names common to multiple propositions in view of potential for inference
   - Formalize all propositions holistically

8. **Formalize propositions**
   - Formalize only new propositions
   - Maintain consistency of predicates and names with previous snapshot

9. **Evaluate validity of formal inferences**
   - Do the same as 2, 3, 4, and 5 above, but only with respect to the formalizations of 7 and 8
   - Unlike 1-8, this task must not be passed full context; content is omitted to avoid distraction

### Solution: New Agent Taxonomy

#### **Core Agent Types**

**1. Content Evaluation Agent** (Evaluates truth, validity, coherence, and identifies weak inferences in natural language content)
```typescript
interface ContentEvaluationAgent {
  input: AgentInput  // Receives steps without formalization attributes
  output: ContentEvaluationResult[]
}
```

**2. Formal Evaluation Agent** (Evaluates validity of formalized logic)
```typescript
interface FormalEvaluationAgent {
  input: AgentInput  // Receives steps without natural language content
  output: FormalEvaluationResult[]
}
```

**3. Formalization Agent** (Converts natural language to formal logic)
```typescript
interface FormalizationAgent {
  input: AgentInput
  output: FormalizationResult[]
}
```

**4. Improvement Agent** (Recommends enhancements and restructuring)
```typescript
interface ImprovementAgent {
  input: AgentInput
  output: ImprovementResult[]
}
```

#### **Agent Hierarchy and Dependencies**
```
Content Evaluation Agent
├── Evaluates truth of propositions
├── Evaluates validity of natural language inferences
├── Checks coherence of proposition sets
└── Identifies weak inferences in natural language

Formalization Agent
├── Formalizes individual propositions
└── Formalizes entire arguments holistically

Formal Evaluation Agent (depends on: Formalization Agent)
├── Evaluates validity of formalized inferences
├── Checks coherence of formalized propositions
└── Identifies weakest formal inferences

Improvement Agent (depends on: Content Evaluation Agent)
├── Recommends proposition rewrites and restructuring
├── Recommends step reordering and restructuring
└── Identifies missing premises for weak inferences
```

## 3. Trigger Mechanism Rearchitecture

### Problem
Current triggering is reactive only to argument changes, limiting agent autonomy and continuous improvement. Agents work in isolation without considering the full context of previous results and related documents.

### Solution: Adaptive Context-Aware Trigger System

#### **Context-Aware Agent Input**
```typescript
interface ContextAwareAgentInput extends AgentInput {
  // Full context including all previous agent results
  context: {
    assumptions: Step[]
    argument: Step[]
    file_ids: string[]
    user_preferences: UserPreferences
    previous_agent_results: AgentResult[]  // Results from all previous agent runs
    document_context: DocumentContext[]    // Extracted content from PDFs and other files
  }
  
  // Agent decision making
  agent_decisions: {
    can_trigger_other_agents: boolean
    can_revisit_previous_work: boolean
    can_use_document_context: boolean
  }
}
```

#### **Document Context Integration**
```typescript
interface DocumentContext {
  file_id: string
  filename: string
  extracted_content: string
  relevance_score: number
  sections: DocumentSection[]
}

interface DocumentSection {
  content: string
  page_number: number
  relevance_to_argument: number
  key_concepts: string[]
}
```

#### **Direct Agent Handoff via Tool Calling**
```typescript
interface AgentTool {
  name: string
  description: string
  parameters: {
    type: "object"
    properties: {
      agent_type: { type: "string" }
      target_content: { type: "string" }
      context: { type: "object" }
      reasoning: { type: "string" }
    }
    required: ["agent_type", "reasoning"]
  }
}

// Each agent has access to tools for calling other agents
const agentTools = [
  {
    name: "trigger_content_evaluation",
    description: "Hand off to content evaluation agent for truth, validity, and coherence analysis",
    parameters: {
      type: "object",
      properties: {
        target_content: { type: "string", description: "Content to evaluate" },
        context: { type: "object", description: "Full conversation context" },
        reasoning: { type: "string", description: "Why this evaluation is needed" }
      },
      required: ["reasoning"]
    }
  },
  {
    name: "trigger_formalization", 
    description: "Hand off to formalization agent to convert natural language to formal logic",
    parameters: {
      type: "object",
      properties: {
        target_content: { type: "string", description: "Content to formalize" },
        context: { type: "object", description: "Full conversation context" },
        reasoning: { type: "string", description: "Why formalization is needed" }
      },
      required: ["reasoning"]
    }
  },
  {
    name: "trigger_formal_evaluation",
    description: "Hand off to formal evaluation agent for logical validity analysis",
    parameters: {
      type: "object", 
      properties: {
        target_content: { type: "string", description: "Formalized content to evaluate" },
        context: { type: "object", description: "Full conversation context" },
        reasoning: { type: "string", description: "Why formal evaluation is needed" }
      },
      required: ["reasoning"]
    }
  },
  {
    name: "trigger_improvement",
    description: "Hand off to improvement agent for recommendations and restructuring",
    parameters: {
      type: "object",
      properties: {
        target_content: { type: "string", description: "Content to improve" },
        context: { type: "object", description: "Full conversation context" },
        reasoning: { type: "string", description: "Why improvement is needed" }
      },
      required: ["reasoning"]
    }
  }
]
```

#### **Agent Handoff Coordinator**
```typescript
class AgentHandoffCoordinator {
  // Track agent call chains to prevent infinite loops
  private callChains: Map<string, string[]> = new Map()
  
  // Handle direct agent handoffs
  async handleAgentHandoff(
    fromAgent: string, 
    toAgent: string, 
    context: ContextAwareAgentInput,
    reasoning: string
  ): Promise<void> {
    // Check for infinite loops
    const callChain = this.callChains.get(context.conversation_id) || []
    if (this.wouldCreateLoop(callChain, toAgent)) {
      return // Prevent the handoff
    }
    
    // Update call chain
    this.callChains.set(context.conversation_id, [...callChain, toAgent])
    
    // Execute the handoff
    await this.executeAgent(toAgent, context, reasoning)
  }
  
  // Check iteration limits
  private wouldCreateLoop(callChain: string[], nextAgent: string): boolean {
    // Simple loop detection - could be more sophisticated
    return callChain.length > 10 || callChain.includes(nextAgent)
  }
  
  // Execute agent with full context
  private async executeAgent(
    agentType: string, 
    context: ContextAwareAgentInput,
    reasoning: string
  ): Promise<void> {
    // Agent gets full context including previous results and documents
    // Agent can make tool calls to other agents
    // Results are accumulated in the conversation context
    
    // TODO: Need to resolve conflict between full context handoff and content filtering
    // - Content Evaluation Agent: needs natural language but should NOT see formalizations
    // - Formal Evaluation Agent: needs formalizations but should NOT see natural language content
    // - Direct handoff requires full context to be passed between agents
    // Potential solutions:
    // 1. Context filtering in handoff coordinator
    // 2. Separate context objects for different agent types
    // 3. Agent-specific handoff tools with filtered context
  }
}
```

#### **Agent Decision Making**
```typescript
interface AgentHandoffDecision {
  agent_type: string
  reasoning: string
  target_content: string
  confidence: number
  expected_outcome: string
}
```

## 4. Snapshot Association

### Problem
Agents currently only associate with conversations, missing the rich context of conversation history and evolution. Managing full historical context is complex and may be excessive.

### Solution: Stale Results Propagation System

#### **Stale Results Propagation**
```typescript
interface SnapshotWithStaleResults {
  snapshot_id: string
  conversation_id: string
  
  // Current state
  assumptions: Step[]
  argument: Step[]
  
  // Stale results from previous snapshot (marked for replacement)
  stale_results: {
    content_evaluation: AgentResult[]  // Marked as stale
    formalization: AgentResult[]       // Marked as stale  
    formal_evaluation: AgentResult[]   // Marked as stale
    improvement: AgentResult[]         // Marked as stale
  }
  
  // Metadata
  created_at: number
  last_modified: number
  version: number
}

interface StaleResult {
  original_result: AgentResult
  marked_stale_at: number
  replacement_priority: number  // Higher priority = replace first
}

interface StaleResultsPropagation {
  // When user makes changes, copy previous agent results as stale
  copyStaleResults(fromSnapshot: ConversationSnapshot, toSnapshot: ConversationSnapshot): void
  
  // Agents replace stale results rather than filling in empty space
  replaceStaleResults(agentType: string, newResults: AgentResult[]): void
  
  // Benefits:
  // - No need for complex historical context
  // - Agents work on replacement rather than completion
  // - Simpler state management
  // - Handles rapid user changes naturally
}
```

## 5. TTL Implementation

### Problem
Agent results persist indefinitely, leading to stale data and resource waste.

### Solution: Multi-Level TTL System

#### **TTL Configuration**
```typescript
interface TTLConfig {
  // Result-level TTLs
  result_ttls: {
    discovery_results: number  // seconds
    analysis_results: number
    formalization_results: number
    improvement_results: number
    synthesis_results: number
  }
  
  // Context-level TTLs
  context_ttls: {
    snapshot_context: number
    file_context: number
    user_preferences: number
  }
  
  // Agent-level TTLs
  agent_ttls: {
    agent_session: number
    agent_memory: number
    agent_cache: number
  }
}
```

#### **TTL Management System**
```typescript
class TTLManager {
  // Result expiration
  scheduleResultExpiration(result_id: string, ttl_seconds: number): void
  extendResultTTL(result_id: string, extension_seconds: number): void
  cleanupExpiredResults(): void
  
  // Context expiration
  scheduleContextExpiration(context_id: string, ttl_seconds: number): void
  refreshContextTTL(context_id: string): void
  
  // Agent session management
  scheduleAgentSessionExpiration(agent_id: string, ttl_seconds: number): void
  keepAgentSessionAlive(agent_id: string): void
}
```

#### **TTL-Aware Result Storage**
```typescript
interface TTLResult {
  id: string
  data: any
  created_at: number
  expires_at: number
  ttl_seconds: number
  auto_extend: boolean
  extension_conditions: ExtensionCondition[]
}

interface ExtensionCondition {
  type: 'user_activity' | 'agent_activity' | 'relevance_threshold'
  condition_data: any
  extension_seconds: number
}
```

#### **Implementation Features**
1. **Automatic Cleanup**: Background process removes expired results
2. **Smart Extensions**: TTLs extend based on user activity and relevance
3. **Graceful Degradation**: Expired results marked as stale but not immediately deleted
4. **User Control**: Users can manually extend or expire results

## 6. Loop Closure: Agent Results Integration

### Problem
The current system has a critical gap where agent results are not properly integrated back into the system:

1. **Agent results are isolated** - Results from earlier agents aren't available to later agents
2. **No user review mechanism** - Users can't review/accept/reject agent results before they're used
3. **Frontend-backend disconnect** - Agent results don't update the frontend argument state
4. **Dependency chain broken** - Later agents can't access results from earlier agents

### Solution: Systematic Agent Results Integration

#### **Agent Results Integration Flow**
```typescript
interface AgentResultsIntegration {
  // Current flow: Agent Results → Argument Steps → Backend
  // Need to make this systematic and bidirectional
  
  // Agent results available to dependent agents
  agent_results: {
    content_evaluation: ContentEvaluationResult[]  // truth/validity values
    formalization: FormalizationResult[]           // formalization strings
    formal_evaluation: FormalEvaluationResult[]    // formal validity values
    improvement: ImprovementResult[]               // improvement suggestions
  }
  
  // Integration status tracking
  integration_status: {
    content_evaluation_in_argument: boolean  // truth/valid copied to argument steps
    formalizations_in_argument: boolean      // formalization copied to argument steps
    formal_evaluation_in_argument: boolean   // formal validity copied to argument steps
  }
  
  // User review/approval workflow
  user_reviews: {
    [result_id: string]: {
      status: 'pending' | 'approved' | 'rejected' | 'user_modified'
      user_notes?: string
      reviewed_at: number
      applied_to_argument: boolean
    }
  }
}
```

#### **User Review Interface**
```typescript
interface UserReviewInterface {
  // Review formalization results
  reviewFormalizations(formalizations: FormalizationResult[]): Promise<ReviewDecision[]>
  
  // Review content evaluation results  
  reviewContentEvaluation(evaluation: ContentEvaluationResult[]): Promise<ReviewDecision[]>
  
  // Review improvement suggestions
  reviewImprovements(improvements: ImprovementResult[]): Promise<ReviewDecision[]>
  
  // Apply approved results to argument
  applyApprovedResults(approved_results: AgentResult[]): Promise<void>
}

interface ReviewDecision {
  result_id: string
  decision: 'approve' | 'reject' | 'modify'
  modifications?: any
  notes?: string
}
```

#### **Agent Results Propagation**
```typescript
interface AgentResultsPropagation {
  // Make results available to dependent agents
  propagateResultsToAgents(
    source_agent: string,
    results: AgentResult[],
    target_agents: string[]
  ): Promise<void>
  
  // Update argument state with approved results
  updateArgumentWithResults(
    conversation_id: string,
    snapshot_id: string,
    approved_results: AgentResult[]
  ): Promise<void>
  
  // Notify frontend of result updates
  notifyFrontendOfResults(
    conversation_id: string,
    results: AgentResult[]
  ): Promise<void>
}
```

#### **Frontend Integration Points**
```typescript
interface FrontendAgentIntegration {
  // Display pending reviews
  showPendingReviews(): void
  
  // Apply approved results to argument
  applyResultsToArgument(results: AgentResult[]): void
  
  // Update argument display with agent insights
  updateArgumentWithAgentInsights(insights: AgentInsight[]): void
  
  // Show agent result history
  showAgentResultHistory(): void
}

interface AgentInsight {
  type: 'truth_score' | 'validity_score' | 'formalization' | 'improvement'
  target_step: string
  value: any
  confidence: number
  reasoning: string
}
```

#### **Implementation Strategy**

**Phase 1: Agent Results Access (Immediate)**
- Modify agent input to include previous agent results from argument steps
- Update `AgentCoordinator` to extract truth/validity values and formalizations from argument steps
- Implement result filtering per agent type (content evaluator gets truth/validity, formal evaluator gets formalizations)
- Update agent prompts to handle and use previous results from argument data

**Phase 2: User Review System (Week 2)**
- Create review interface for formalization results before they're copied to argument steps
- Implement approval/rejection workflow for formalizations
- Add user notes and modification capabilities
- Only copy approved formalizations to argument steps
- Allow users to manually edit formalizations in argument steps

**Phase 3: Systematic Integration (Week 3)**
- Make the copying of agent results to argument steps systematic and tracked
- Show which agent results have been integrated into argument steps
- Provide clear indication of pending vs applied results
- Add ability to revert agent result integration

**Phase 4: Advanced Integration (Week 4)**
- Implement result versioning and comparison
- Add result confidence scoring and filtering
- Create result impact analysis (what changes when results are applied)
- Add bulk review and application capabilities
- Support user manual formalization entry

## 7. Frontend Integration

### Problem
Frontend has limited integration with the agent system, showing only basic results.

### Solution: Rich Agent-Frontend Integration

#### **Enhanced Agent Results Display**
```typescript
interface EnhancedAgentResult {
  id: string
  agent_type: string
  operation: string
  
  // Rich result data
  result_data: {
    suggestions: AgentSuggestion[]
    analyses: AnalysisResult[]
    formalizations: FormalizationResult[]
    improvements: ImprovementResult[]
    synthesis: SynthesisResult[]
  }
  
  // Interactive elements
  interactions: {
    can_approve: boolean
    can_reject: boolean
    can_modify: boolean
    can_apply: boolean
  }
  
  // Metadata
  metadata: {
    confidence: number
    reasoning: string
    created_at: number
    expires_at: number
    relevance_score: number
  }
}
```

#### **Agent Status Dashboard**
```typescript
interface AgentStatusDashboard {
  // Active agents
  active_agents: {
    agent_type: string
    status: 'running' | 'pending' | 'completed' | 'failed'
    progress: number
    estimated_completion: number
  }[]
  
  // Recent results
  recent_results: EnhancedAgentResult[]
  
  // System health
  system_health: {
    queue_size: number
    average_response_time: number
    error_rate: number
    resource_usage: ResourceUsage
  }
}
```

#### **Interactive Agent Controls**
```typescript
interface AgentControls {
  // Manual triggering
  triggerAgent(agent_type: string, target: string): Promise<void>
  
  // Result management
  approveResult(result_id: string): Promise<void>
  rejectResult(result_id: string): Promise<void>
  modifyResult(result_id: string, modifications: any): Promise<void>
  
  // TTL management
  extendResultTTL(result_id: string, extension_seconds: number): Promise<void>
  expireResult(result_id: string): Promise<void>
  
  // Agent configuration
  configureAgent(agent_type: string, config: AgentConfig): Promise<void>
  pauseAgent(agent_type: string): Promise<void>
  resumeAgent(agent_type: string): Promise<void>
}
```

#### **Real-Time Updates**
```typescript
interface AgentRealTimeUpdates {
  // WebSocket events
  onAgentStarted(agent_id: string, agent_type: string): void
  onAgentCompleted(agent_id: string, result: EnhancedAgentResult): void
  onAgentFailed(agent_id: string, error: string): void
  
  // Result updates
  onResultExpired(result_id: string): void
  onResultExtended(result_id: string, new_expiry: number): void
  
  // System updates
  onSystemHealthUpdate(health: SystemHealth): void
  onQueueUpdate(queue_size: number): void
}
```

## Implementation Phases

### Phase 1: Foundation (Weeks 1-2)
1. ✅ Implement `AgentInput` schema with context filtering
2. ✅ Update `Step` model to include `formalization`, `valid_content`, and `valid_formal` attributes
3. ✅ Set up minimal TTL functionality in `AgentResultManager` with cleanup on `/argue` endpoint
4. ✅ Implement `StaleResultsPropagation` system

### Phase 1.5: Critical Loop Closure (Immediate Priority)
**Objective**: Close the critical gap where agent results aren't available to dependent agents or users

**Implementation Steps**:

1. **Agent Results Access from Argument Steps (Week 1)**
   - Modify `AgentCoordinator` to extract truth/validity values and formalizations from argument steps
   - Update `create_agent_input()` to include previous agent results from argument data
   - Implement result filtering: content evaluator gets truth/validity values, formal evaluator gets formalization strings
   - Update agent prompts to handle and use previous results from argument steps

2. **User Review System for Formalizations (Week 1)**
   - Create review interface for formalization results before they're copied to argument steps
   - Implement approval/rejection workflow in frontend
   - Add user notes and modification capabilities
   - Only copy approved formalizations to argument steps
   - Allow users to manually edit formalizations in argument steps

3. **Systematic Integration Tracking (Week 2)**
   - Track which agent results have been copied to argument steps
   - Show clear indication of pending vs applied results in frontend
   - Provide ability to revert agent result integration
   - Make the copying process systematic and visible to users

**Success Criteria**:
- Content evaluator results available to improvement agent
- Formalization results require user review before use
- Formal evaluator only uses approved formalizations
- Frontend clearly shows pending vs applied results
- No agent runs without access to required previous results

**Files to Modify**:
- `backend/services/agent_coordinator.py` (modify `create_agent_input`)
- `backend/services/agent_prompts.py` (update prompts to handle previous results)
- `frontend/src/AllAgentResults.tsx` (add review interface)
- `frontend/src/ArgumentEditor.tsx` (integrate approved results)
- `backend/api/agents.py` (add review endpoints)

### Phase 2: Agent Reorganization (Weeks 3-4)

#### Phase 2.1: New Agent Taxonomy Implementation (Week 3)

**Objective**: Implement the four core agent types with proper input/output schemas and filtering

**Prerequisite**: Phase 1.5 (Loop Closure) must be completed first to ensure agents can access required previous results.

**Implementation Steps**:

1. **Evolve Existing Gpt Class**
   - Enhance existing `Gpt` class in `conversation.py` to support agent functionality
   - Add `AgentInput` validation and filtering capabilities
   - Add `AgentResult` standardization
   - Maintain backward compatibility with existing usage

2. ✅ **Update Existing ContentEvaluationAgent**
   - Enhanced existing `ContentEvaluationAgent` in `agents.py`
   - Ensured proper input filtering to exclude formalization data
   - Updated prompts for truth, validity, coherence evaluation
   - Standardized result schema
   - Added weak inference identification prompts
   - **TODO**: Update to use previous agent results from loop closure system

3. ✅ **Update Existing FormalizationAgent**
   - Enhanced existing `FormalizationAgent` in `agents.py`
   - Updated to use `FilteredAgentInput` for proper input handling
   - Enhanced prompts to work with new `AgentInput` structure
   - Standardized result schema with proper JSON structure
   - Added support for existing formalizations for consistency checking
   - **TODO**: Update to use previous content evaluation results

4. ✅ **Update Existing FormEvaluationAgent**
   - ✅ Enhanced existing `FormEvaluationAgent` in `agents.py`
   - ✅ Ensured proper input filtering to exclude natural language content
   - ✅ Updated prompts for formal logic validation
   - ✅ Standardized result schema
   - ✅ Weakest formal inference identification (already provided by `proposition_evaluations` array)
   - ✅ Integrated with user review system via `endorsed` field

5. **Implement Improvement Agent (combining RewriterAgent and ArgumentBuilderAgent)**
   - Complete the existing `RewriterAgent` stub in `agents.py`
   - Incorporate functionality from existing `ArgumentBuilderAgent`
   - Rename to `ImprovementAgent` for clarity
   - Create prompts for recommendation generation
   - Create prompts for proposition rewrite suggestions
   - Create prompts for argument building and enhancement
   - Standardize result schema
   - Add prompts for missing premise identification
   - **TODO**: Update to use content evaluation results from loop closure system

6. ✅ **Update Agent Coordinator**
   - Modified `AgentCoordinator` to support enhanced ContentEvaluationAgent
   - Updated task queueing for new agent hierarchy
   - Implemented proper input filtering per agent type
   - Added agent type-specific result handling
   - **TODO**: Update to include previous agent results in input creation

7. **Update API Endpoints**
   - Update existing `/api/agents` endpoints to work with enhanced agents
   - Update agent status tracking
   - **TODO**: Add review endpoints for user approval workflow

**Success Criteria**:
- All four agent types implemented and functional
- Proper input filtering working for each agent type
- Agent results properly structured and typed
- Agent coordinator supports new taxonomy
- API endpoints updated and tested

**Files to Modify/Create**:
- `backend/agents/base_agent.py` (new)
- `backend/agents/content_evaluation_agent.py` (new)
- `backend/agents/formalization_agent.py` (new)
- `backend/agents/formal_evaluation_agent.py` (new)
- `backend/agents/improvement_agent.py` (new)
- `backend/agents/agent_factory.py` (new)
- `backend/services/agent_coordinator.py` (modify)
- `backend/api/agents.py` (modify)
- `backend/schemas/agent_results.py` (new)
- `backend/tests/test_new_agent_taxonomy.py` (new)

#### Phase 2.2: Agent Migration and Handoff (Week 4)

2. Migrate existing agents to new types with proper input filtering
3. Set up direct agent handoff via OpenAI tool calling
4. Create `AgentHandoffCoordinator` with loop prevention

### Phase 3: Advanced Features (Weeks 5-6)
1. Implement document context integration for PDFs and files
2. Add context-aware agent decision making
3. Enhance TTL system with smart extensions
4. Resolve content filtering vs. full context handoff conflict

### Phase 4: Frontend Integration (Weeks 7-8)
1. Create enhanced result display components with stale result indicators
2. Implement agent status dashboard with real-time handoff tracking
3. Add interactive agent controls for manual triggering
4. Set up WebSocket-based real-time updates

### Phase 5: Testing and Optimization (Weeks 9-10)
1. Comprehensive testing of agent handoff chains and loop prevention
2. Performance optimization of context filtering and stale result propagation
3. User experience refinement with progressive disclosure
4. Documentation and training materials

## Success Metrics

### Technical Metrics
- **Response Time**: Agent response time < 5 seconds for 95% of requests
- **Accuracy**: Agent suggestion accuracy > 80% user approval rate
- **Resource Usage**: < 50% increase in memory/CPU usage
- **Reliability**: < 1% error rate for agent operations

### User Experience Metrics
- **Engagement**: 50% increase in user interaction with agent suggestions
- **Satisfaction**: 4.5+ star rating for agent functionality
- **Efficiency**: 30% reduction in time to complete arguments
- **Discovery**: 40% increase in users discovering new argument elements

### System Health Metrics
- **TTL Effectiveness**: 90% of expired results properly cleaned up
- **Cascade Efficiency**: 80% of cascades complete within 30 seconds
- **Snapshot Relevance**: 85% of agent results relevant to current snapshot
- **Trigger Accuracy**: 90% of triggers result in useful agent activity

## Risk Mitigation

### Technical Risks
1. **Performance Impact**: Implement gradual rollout with monitoring
2. **Data Loss**: Comprehensive backup and rollback procedures
3. **Complexity**: Modular implementation with clear interfaces
4. **Integration Issues**: Extensive testing and backward compatibility

### User Experience Risks
1. **Overwhelming Interface**: Progressive disclosure of advanced features
2. **Learning Curve**: Comprehensive onboarding and help system
3. **Unwanted Suggestions**: User control over agent activity levels
4. **Performance Perception**: Real-time feedback and progress indicators

## 7. Frontend State Management Rearchitecture

### Problem
The frontend application had scattered state management with conversation-related state and logic distributed across local React component state and hooks, leading to:
- **Prop drilling** - Passing state down multiple component levels
- **Inconsistent state** - State managed in different places with different patterns
- **Complex component interfaces** - Components requiring many props for state access
- **Difficult debugging** - State changes happening in multiple locations
- **Poor separation of concerns** - UI components managing business logic

### Solution: Centralized Zustand State Management

#### **Store Architecture**
```typescript
interface ConversationState {
  // Core state
  conversations: ConversationType[]
  currentConversationIndex: number
  currentSnapshotIndex: number
  nextConversationId: number
  userMode: 'waiting' | 'ready' | 'input'
  snapshotRenderCount: number
  sessionId: string
  lastFailedOperation: ApiOperationInfo | null
  
  // State management functions
  updateCurrentConversation: (conversation: ConversationType) => void
  saveConversationName: (conversationId: number, name: string) => void
  setCurrentConversationIndex: (index: number) => void
  setCurrentSnapshotIndex: (index: number) => void
  setUserMode: (mode: 'waiting' | 'ready' | 'input') => void
  setSnapshotRenderCount: (count: number) => void
  setNextConversationId: (id: number) => void
  setLastFailedOperation: (operation: ApiOperationInfo | null) => void
  
  // Data access functions
  getCurrentConversationState: () => { conversation: ConversationType, snapshotIndex: number }
  getCurrentConversationId: () => number
  
  // Conversation management
  createConversationFromProposition: (proposition: string) => void
  createConversation: (initPrompt?: string) => void
  
  // Snapshot operations
  applyNewArgument: (responseData: any) => void
  applyAgentResults: (changes: AgentResultChanges) => void
  
  // API coordination
  makeApiCall: (operation: ApiOperationInfo) => Promise<void>
}

interface AgentResultChanges {
  truthUpdates?: { symbol: string, value: string }[]
  validityUpdates?: { symbol: string, value: string }[]
  formalizationUpdates?: { symbol: string, formalization: any }[]
  formalValidityUpdates?: { symbol: string, value: string }[]
  formalizationDefinitions?: any
}
```

#### **Component Integration**
```typescript
// Before: Components with many props
function Conversation({ 
  conversation, 
  setConversation, 
  sessionId, 
  userMode, 
  setUserMode,
  currentSnapshotIndex,
  setCurrentSnapshotIndex,
  // ... many more props
}) { ... }

// After: Components access state directly
function Conversation() {
  const { 
    conversations, 
    currentConversationIndex, 
    currentSnapshotIndex,
    updateCurrentConversation 
  } = useConversationStore()
  // ... component logic
}
```

#### **Data Flow Architecture**
```typescript
// 1. Components access state via store
const { getCurrentConversationState, applyNewArgument } = useConversationStore()

// 2. User actions dispatch to store
const handleUserAction = () => {
  makeApiCall({
    url: '/api/argument/user-justify',
    data: currentSnapshot,
    onSuccess: applyNewArgument,  // Store handles state update
    onFinally: () => setUserMode('ready')
  })
}

// 3. Agent results processed and applied
const applyAgentResultsToSnapshot = (newResultsByAgent: ResultsByAgent) => {
  // Component parses results into structured changes
  const changes = parseAgentResults(newResultsByAgent)
  
  // Store applies changes to its own state
  applyAgentResults(changes)
}
```

### Implementation Results

#### **Completed Work ✅**

**1. Store Foundation**
- ✅ **Created centralized Zustand store** (`conversationStore.ts`)
- ✅ **Defined core state structure** with conversations, snapshots, indices, and user modes
- ✅ **Implemented initial snapshot system** where all conversations start with an empty snapshot (index 0)
- ✅ **Added session management** with `sessionId` and `lastFailedOperation` tracking

**2. State Migration**
- ✅ **Moved `sessionId`** from local hooks to store
- ✅ **Moved `userMode`** from local hooks to store  
- ✅ **Moved `currentSnapshotIndex`** from local hooks to store
- ✅ **Moved `snapshotRenderCount`** from local hooks to store
- ✅ **Moved conversation data** from props to store access
- ✅ **Moved `getCurrentConversationState`** to store
- ✅ **Moved `getCurrentConversationId`** to store

**3. Function Migration**
- ✅ **Moved `createConversationFromProposition`** to store
- ✅ **Moved `createConversation`** to store
- ✅ **Moved `setUserMode`** to store
- ✅ **Moved `setCurrentConversationIndex`** to store
- ✅ **Moved `setSnapshotRenderCount`** to store
- ✅ **Moved `setNextConversationId`** to store
- ✅ **Moved `setLastFailedOperation`** to store

**4. API Call Management**
- ✅ **Implemented `makeApiCall`** in store with error handling
- ✅ **Created `applyNewArgument`** for handling API responses and creating new snapshots
- ✅ **Refactored handlers** to use `applyNewArgument` for snapshot updates
- ✅ **Maintained async operations in hooks** while dispatching pure actions to store

**5. Agent Results Processing**
- ✅ **Implemented `applyAgentResults`** in store for applying agent result changes
- ✅ **Refactored `AllAgentResults`** to parse agent results and send structured changes to store
- ✅ **Proper separation of concerns**: Component parses, store applies changes to state
- ✅ **Eliminated snapshot construction** outside the store

**6. Component Cleanup**
- ✅ **Removed prop drilling** from `Conversation`, `AllAgentResults`, and other components
- ✅ **Updated `useConversationState`** to get state from store instead of props
- ✅ **Updated `useConversationActions`** to get actions from store instead of props
- ✅ **Simplified component interfaces** by removing unnecessary props

**7. Code Cleanup**
- ✅ **Removed unused functions**: `saveSnapshot`, `saveSnapshotInPlace`, `addConversation`
- ✅ **Removed commented-out code** and dead functions
- ✅ **Cleaned up redundant parameters** and unused variables
- ✅ **Fixed linter errors** and type issues

#### **Current Architecture**

**Store Responsibilities**
- **State management**: Conversations, snapshots, indices, user modes
- **Snapshot operations**: Creating new snapshots, applying changes to current snapshot
- **API coordination**: Making calls, handling responses, error management
- **State consistency**: Ensuring proper snapshot sequencing and state updates

**Component Responsibilities**
- **UI rendering**: Displaying conversation state from store
- **User interactions**: Dispatching actions to store
- **Agent result parsing**: Converting backend responses to structured changes
- **Side effects**: Polling, API calls, lifecycle management

**Data Flow**
1. **Components** access state via `useConversationStore()`
2. **User actions** dispatch to store functions
3. **API calls** happen in hooks, results dispatched to store
4. **Store** manages all state updates and snapshot operations
5. **Components** re-render automatically via Zustand subscriptions

#### **Benefits Achieved**
- ✅ **Centralized state management** - Single source of truth for conversation state
- ✅ **Eliminated prop drilling** - Components access state directly from store
- ✅ **Improved state consistency** - Store ensures proper snapshot sequencing
- ✅ **Better separation of concerns** - Clear boundaries between state management and UI
- ✅ **Simplified component interfaces** - Fewer props, cleaner component signatures
- ✅ **Type safety** - Proper TypeScript interfaces for all state operations
- ✅ **Error handling** - Centralized error management in store

### Integration with Agent System

The frontend state management rearchitecture provides a solid foundation for the agent system improvements:

**1. Agent Results Integration**
- Store's `applyAgentResults` function provides clean interface for agent result updates
- Structured changes ensure type safety and proper state updates
- Component parsing ensures proper separation of concerns

**2. User Review System**
- Store can easily add user review state management
- Components can access review state directly without prop drilling
- Review decisions can be dispatched to store for state updates

**3. Real-time Updates**
- Zustand subscriptions enable real-time updates from agent system
- Store can handle agent status updates and result notifications
- Components automatically re-render when agent state changes

**4. Error Handling**
- Centralized error management in store handles agent failures
- `lastFailedOperation` tracking provides user feedback
- Retry mechanisms can be implemented at store level

## Conclusion

This rearchitecture plan transforms Dianoia's agent system from a reactive, conversation-focused system into a proactive, snapshot-aware, and user-controlled intelligent assistant. The phased implementation ensures minimal disruption while delivering significant improvements in functionality, performance, and user experience.

The new architecture provides:
- **Standardized Input**: Consistent data format across all agents
- **Clear Agent Roles**: Well-defined responsibilities and hierarchies
- **Flexible Triggering**: Multiple ways to activate agents based on needs
- **Rich Context**: Full awareness of conversation history and evolution
- **Efficient Resource Management**: Smart TTLs and cleanup
- **Enhanced User Experience**: Rich frontend integration and controls
- **Centralized State Management**: Single source of truth for frontend state

This foundation enables future enhancements such as agent learning, collaborative agent networks, and advanced reasoning capabilities.

## 8. Data Contract Standardization

### Problem
Currently, the frontend and backend use different data structures that require filtering and transformation:
- Frontend sends `ConversationSnapshot` with fields like `argMode` that backend doesn't need
- Backend expects `Arguments` schema that doesn't match frontend exactly
- `FilteredAgentInput` classes are needed to transform data for specific agents
- Schema mismatches cause validation errors and require workarounds

### Solution: Identical Data Contracts

Create standardized data classes that are identical between frontend and backend:

#### Core Data Classes
```typescript
// Shared between frontend and backend
interface Step {
  symbol: string
  proposition: string
  justifiers: string[]
  truth: string
  valid: string
  formalization?: Formalization
}

interface Formalization {
  ascii: string
  json_structure: any
  endorsed: boolean
}

interface AgentArguments {
  assumptions: Step[]
  argument: Step[]
  explanation: string | null
  file_ids: string[]
}
```

#### Metadata Separation
```typescript
// Frontend-only metadata
interface FrontendMetadata {
  argMode: 'thesis' | 'development'
  snapshotIndex: number
  conversationId: number
  // ... other UI state
}

// Backend-only metadata
interface BackendMetadata {
  conversation_id: string
  snapshot_id: string
  agent_coordination: AgentCoordinationData
  // ... other backend state
}
```

#### Benefits
1. **No filtering needed**: Frontend and backend use identical core data structures
2. **Type safety**: Shared TypeScript interfaces ensure consistency
3. **Clear separation**: UI state and backend state are clearly separated
4. **Simplified agents**: Agents work with clean, standardized data
5. **Easier testing**: Identical schemas make testing more straightforward

#### Implementation Plan
1. Create shared data contracts in a common location
2. Update frontend to use `AgentArguments` instead of `ConversationSnapshot` for API calls
3. Update backend to use `AgentArguments` instead of `Arguments`
4. Remove `FilteredAgentInput` classes - agents work with standard data
5. Separate metadata into frontend/backend specific structures
6. Update all agent implementations to use standardized interfaces

This approach eliminates the need for data transformation and filtering, making the system more maintainable and reducing potential for schema mismatches.
