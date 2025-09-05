import { useState, useEffect, useRef } from 'react'
import axios from 'axios'
import { useConversationStore } from './conversationStore'

const VITE_API_BASE_URL = import.meta.env.VITE_API_BASE_URL

type AgentResult = {
  agent_type: string
  operation: string
  result_content: any
  confidence: number
  reasoning: string
  processed_at: number
  target_metadata?: any
  snapshot_id: string
}

type ResultsByAgent = {
  [agentType: string]: AgentResult[]
}

export default function AllAgentResults() {
  const { sessionId, getCurrentConversationState, getCurrentConversationId, currentSnapshotIndex, 
    applyAgentResults, saveAgentResults, getAgentResults } = useConversationStore()
  const conversationId = getCurrentConversationId()
  
  const [resultsByAgent, setResultsByAgent] = useState<ResultsByAgent>({})
  const [error, setError] = useState<string | null>(null)
  const [activeTasks, setActiveTasks] = useState<any[]>([])
  const [activeTaskCount, setActiveTaskCount] = useState<number>(0)
  const [acceptedRecommendations, setAcceptedRecommendations] = useState<Set<string>>(new Set())
  const [rejectedRecommendations, setRejectedRecommendations] = useState<Set<string>>(new Set())
  const tasksCompleteRef = useRef<boolean>(false)
  const currentPollingSnapshotRef = useRef<number>(-1)
  const intervalRef = useRef<number | null>(null)
  const currentFetchRef = useRef<Promise<void> | null>(null)

  // Helper function to get current snapshot
  const getCurrentSnapshot = () => {
    const { conversation, snapshotIndex: currentSnapshotIndex } = getCurrentConversationState()
    const lastSnapshot = conversation.snapshots[currentSnapshotIndex]
    return lastSnapshot || { assumptions: [], argument: [], explanation: '', file_ids: [] }
  }

  // Helper function to get agent display name
  const getAgentDisplayName = (agentType: string) => {
    switch (agentType) {
      case 'content_evaluator': return '🔍 Content Evaluator'
      case 'form_evaluator': return '🧮 Formal Logic Evaluator'
      case 'formalizer': return '📐 Formalization Agent'
      case 'improver': return '🎯 Improvement Agent'
      default: return agentType
    }
  }

  // Load agent results from store when snapshot changes
  useEffect(() => {
    const storedResults = getAgentResults(conversationId, currentSnapshotIndex)
    setResultsByAgent(storedResults)
  }, [currentSnapshotIndex, conversationId, getAgentResults])

  // Note: This component resets its state when snapshotIndex changes to ensure
  // proper behavior with undo/redo operations. Each snapshot will fetch its own
  // agent results independently.

  // Check if all formalizations are endorsed (for UI display purposes)
  const areAllFormalizationsEndorsed = () => {
    const currentSnapshot = getCurrentSnapshot()
    const allSteps = [...currentSnapshot.argument, ...currentSnapshot.assumptions]
    
    // Check that all steps have formalizations and all formalizations are endorsed
    return allSteps.length > 0 && allSteps.every((step: any) => step.formalization?.endorsed)
  }

  // Apply agent results to argument steps
  const applyAgentResultsToSnapshot = (newResultsByAgent: ResultsByAgent) => {
    const changes: any = {}

    // Parse ContentEvaluationAgent results
    const contentResults = newResultsByAgent['content_evaluator']
    if (contentResults && contentResults.length > 0) {
      const latestContentResult = contentResults[contentResults.length - 1]
      const resultContent = latestContentResult.result_content

      // Parse truth evaluations
      if (resultContent.truth_evaluations) {
        changes.truthUpdates = resultContent.truth_evaluations.map((evaluation: any) => ({
          symbol: evaluation.symbol,
          value: evaluation.truth_value.toString()
        }))
      }

      // Parse validity evaluations
      if (resultContent.validity_evaluations) {
        changes.validityUpdates = resultContent.validity_evaluations.map((evaluation: any) => ({
          symbol: evaluation.symbol,
          value: evaluation.validity_value.toString()
        }))
      }
    }

    // Parse FormalizationAgent results
    const formalizationResults = newResultsByAgent['formalizer']
    if (formalizationResults && formalizationResults.length > 0) {
      const latestFormalizationResult = formalizationResults[formalizationResults.length - 1]
      const resultContent = latestFormalizationResult.result_content

      // Parse formalizations
      if (resultContent.formalizations) {
        changes.formalizationUpdates = resultContent.formalizations.map((formalization: any) => ({
          symbol: formalization.symbol,
          formalization: {
            ascii: formalization.ascii,
            json_structure: formalization.json_structure,
            endorsed: false
          }
        }))
      }

      // Parse formalization definitions
      if (resultContent.definitions) {
        changes.formalizationDefinitions = resultContent.definitions
      }
    }

    // Parse FormalEvaluatorAgent results
    const formalEvaluatorResults = newResultsByAgent['form_evaluator']
    if (formalEvaluatorResults && formalEvaluatorResults.length > 0) {
      const latestFormalEvaluatorResult = formalEvaluatorResults[formalEvaluatorResults.length - 1]
      const resultContent = latestFormalEvaluatorResult.result_content

      // Parse formal validity evaluations
      if (resultContent.proposition_evaluations) {
        changes.formalValidityUpdates = resultContent.proposition_evaluations.map((evaluation: any) => ({
          symbol: evaluation.symbol,
          value: evaluation.validity.toString()
        }))
      }
    }

    // Apply changes to the store if there are any
    if (Object.keys(changes).length > 0) {
      applyAgentResults(changes)
    }
  }

  const fetchResults = async () => {
    // Prevent concurrent fetches
    if (currentFetchRef.current) {
      return
    }
    
    // Clear the flag synchronously to prevent race conditions
    currentFetchRef.current = (async () => {
      try {
        const response = await axios.get(`${VITE_API_BASE_URL}/api/agents/results`, {
          params: {
            conversation_id: `${sessionId}:${conversationId}`,
            snapshot_id: String(currentSnapshotIndex)
          },
          timeout: 15000 // 15 second timeout
        })
        
        const newResultsByAgent = response.data.results_by_agent || {}
        const newTasksComplete = response.data.tasks_complete || false
        const newActiveTasks = response.data.active_tasks || []
        const newActiveTaskCount = response.data.active_task_count || 0
        const conversationName = response.data.conversation_name
        
        // Handle conversation name if present and different from current
        if (conversationName) {
          const { saveConversationName, getConversationName } = useConversationStore.getState()
          const currentName = getConversationName(conversationId)
          if (currentName !== conversationName) {
            saveConversationName(conversationId, conversationName)
            // console.log(`💾 Saved conversation name: ${conversationName}`)
          }
        }
        
        // Only update if we have new results
        if (JSON.stringify(newResultsByAgent) !== JSON.stringify(resultsByAgent)) {
          setResultsByAgent(newResultsByAgent)
          
          // Store raw agent results by snapshot
          saveAgentResults(conversationId, currentSnapshotIndex, newResultsByAgent)
          
          // Apply results to snapshot (for UI updates)
          applyAgentResultsToSnapshot(newResultsByAgent)
        } else {
          // console.log('⏭️ Skipping update - no new data')
        }
        
        // Update active tasks data
        setActiveTasks(newActiveTasks)
        setActiveTaskCount(newActiveTaskCount)
        
        // Update tasks complete status
        if (newTasksComplete !== tasksCompleteRef.current) {
          tasksCompleteRef.current = newTasksComplete
          
          // Clear interval if tasks are complete
          if (newTasksComplete && intervalRef.current) {
            clearInterval(intervalRef.current)
            intervalRef.current = null
          }
        }
        
      } catch (error: any) {
        console.error('❌ Error fetching agent results:', error)
        setError('Error loading results')
      }
    })()
    
    // Wait for the promise to complete and then clear the flag
    await currentFetchRef.current
    // console.log('🏁 Fetch completed - clearing promise reference')
    currentFetchRef.current = null
  }

  useEffect(() => {
    // Skip fetching if snapshotIndex is less than 1 (no snapshot history yet)
    if (currentSnapshotIndex < 1) {
      return
    }
    
    // Skip if we're already polling for this snapshot
    if (currentPollingSnapshotRef.current === currentSnapshotIndex) {
      return
    }
    
    // Always check with server for latest results, but preserve stored results as initial state
    const storedResults = getAgentResults(conversationId, currentSnapshotIndex)
    setResultsByAgent(storedResults)
    setError(null)
    tasksCompleteRef.current = false
    
    currentPollingSnapshotRef.current = currentSnapshotIndex
    
    // Set up polling every 1 second, but only if tasks are not complete
    const interval = setInterval(() => {
      if (!tasksCompleteRef.current && !currentFetchRef.current) {
        fetchResults()
      }
    }, 1000)
    
    // Store interval reference
    intervalRef.current = interval
    
    return () => {
      clearInterval(interval)
      intervalRef.current = null
    }
  }, [conversationId, sessionId, currentSnapshotIndex])

  // Check if all formalizations are endorsed
  const allFormalizationsEndorsed = areAllFormalizationsEndorsed()


  const renderContentEvaluatorResults = (results: AgentResult[]) => {
    return (
      <div className="space-y-3">
        {results.map((result, index) => (
          <div key={index} className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                📸 Snapshot {result.snapshot_id}
              </span>
              <span className="text-xs text-gray-500">
                {new Date(result.processed_at * 1000).toLocaleTimeString()}
              </span>
            </div>
            <div className="flex justify-between items-start mb-3">
              <span className="font-medium text-purple-700 flex items-center">
                <span className="mr-2">🔍</span>
                Content Evaluator
              </span>
              <span className="text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded">
                {result.confidence.toFixed(2)} confidence
              </span>
            </div>
            {result.result_content && (
              <div className="mt-3 space-y-2">
                {/* Truth Evaluations */}
                {result.result_content.truth_evaluations && result.result_content.truth_evaluations.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-gray-700 mb-2">
                      📊 Truth Evaluations:
                    </div>
                    <div className="space-y-1">
                      {result.result_content.truth_evaluations.map((evaluation: any, index: number) => (
                        <div key={index} className="text-sm p-2 bg-gray-50 rounded border border-gray-200">
                          <div className="flex justify-between items-start">
                            <span className="text-gray-700 flex-1">
                              <span className="font-medium">{evaluation.symbol}:</span> {evaluation.reasoning}
                            </span>
                            <span className={`font-medium ml-2 px-2 py-1 rounded text-xs ${
                              evaluation.truth_value >= 0.8 ? 'bg-green-100 text-green-800' :
                              evaluation.truth_value >= 0.5 ? 'bg-yellow-100 text-yellow-800' :
                              'bg-red-100 text-red-800'
                            }`}>
                              {(evaluation.truth_value * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Validity Evaluations */}
                {result.result_content.validity_evaluations && result.result_content.validity_evaluations.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-gray-700 mb-2">
                      🔗 Validity Evaluations:
                    </div>
                    <div className="space-y-1">
                      {result.result_content.validity_evaluations.map((evaluation: any, index: number) => (
                        <div key={index} className="text-sm p-2 bg-blue-50 rounded border border-blue-200">
                          <div className="flex justify-between items-start">
                            <span className="text-gray-700 flex-1">
                              <span className="font-medium">{evaluation.symbol}:</span> {evaluation.reasoning}
                            </span>
                            <span className={`font-medium ml-2 px-2 py-1 rounded text-xs ${
                              evaluation.validity_value >= 0.8 ? 'bg-green-100 text-green-800' :
                              evaluation.validity_value >= 0.5 ? 'bg-yellow-100 text-yellow-800' :
                              'bg-red-100 text-red-800'
                            }`}>
                              {(evaluation.validity_value * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Incoherent Sets */}
                {result.result_content.incoherent_sets && result.result_content.incoherent_sets.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-red-700 mb-2">
                      ⚠️ Incoherent Sets:
                    </div>
                    <div className="space-y-2">
                      {result.result_content.incoherent_sets.map((incoherentSet: any, iIndex: number) => (
                        <div key={iIndex} className="text-sm p-2 bg-red-50 rounded border border-red-200">
                          <div className="flex justify-between items-start">
                            <span className="text-red-700 flex-1">
                              <span className="font-medium">Steps {incoherentSet.symbols.join(', ')}:</span>
                              <span className="ml-2 text-xs">
                                {incoherentSet.incoherence_value === 1.0 ? 'Logical Contradiction' : 
                                 `Incoherence Level: ${(incoherentSet.incoherence_value * 100).toFixed(0)}%`}
                              </span>
                            </span>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Logical Issues */}
                {result.result_content.logical_issues && result.result_content.logical_issues.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-red-700 mb-2">
                      ⚠️ Logical Issues:
                    </div>
                    <ul className="space-y-1">
                      {result.result_content.logical_issues.map((issue: string, iIndex: number) => (
                        <li key={iIndex} className="text-sm text-red-700 p-2 bg-red-50 rounded border border-red-200">
                          {issue}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {/* Recommendations */}
                {result.result_content.recommendations && result.result_content.recommendations.length > 0 && (
                  <div className="mt-3">
                    <div className="text-sm font-medium text-blue-700 mb-2">
                      💡 Recommendations:
                    </div>
                    <ul className="space-y-1">
                      {result.result_content.recommendations.map((rec: string, rIndex: number) => (
                        <li key={rIndex} className="text-sm text-blue-700 p-2 bg-blue-50 rounded border border-blue-200">
                          {rec}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  const renderFormEvaluatorResults = (results: AgentResult[]) => {
    return (
      <div className="space-y-3">
        {results.map((result, index) => (
          <div key={index} className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                📸 Snapshot {result.snapshot_id}
              </span>
              <span className="text-xs text-gray-500">
                {new Date(result.processed_at * 1000).toLocaleTimeString()}
              </span>
            </div>
            <div className="flex justify-between items-start mb-3">
              <span className="font-medium text-orange-700 flex items-center">
                <span className="mr-2">🧮</span>
                Formal Logic Evaluator
              </span>
              <span className="text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded">
                {result.confidence.toFixed(2)} confidence
              </span>
            </div>
            <div className="text-sm text-gray-700 mb-3 p-2 bg-gray-50 rounded">
              💭 {result.reasoning}
            </div>
            
            {/* Argument Validity */}
            {result.result_content?.argument_validity !== undefined && (
              <div className="mt-3">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  🎯 Overall Argument Validity:
                </div>
                <div className={`inline-block px-3 py-1 rounded text-sm font-medium ${
                  result.result_content.argument_validity >= 0.8 ? 'bg-green-100 text-green-800' :
                  result.result_content.argument_validity >= 0.5 ? 'bg-yellow-100 text-yellow-800' :
                  'bg-red-100 text-red-800'
                }`}>
                  {(result.result_content.argument_validity * 100).toFixed(0)}%
                </div>
              </div>
            )}

            {/* Proposition Evaluations */}
            {result.result_content?.proposition_evaluations && result.result_content.proposition_evaluations.length > 0 && (
              <div className="mt-3">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  📊 Proposition Validity Evaluations:
                </div>
                <div className="space-y-2">
                  {result.result_content.proposition_evaluations.map((evaluation: any, index: number) => (
                    <div key={index} className="p-2 bg-gray-50 rounded border border-gray-200">
                      <div className="flex justify-between items-start">
                        <span className="text-gray-700 flex-1">
                          <span className="font-medium">{evaluation.symbol}:</span> {evaluation.reasoning}
                        </span>
                        <span className={`font-medium ml-2 px-2 py-1 rounded text-xs ${
                          evaluation.validity >= 0.8 ? 'bg-green-100 text-green-800' :
                          evaluation.validity >= 0.5 ? 'bg-yellow-100 text-yellow-800' :
                          'bg-red-100 text-red-800'
                        }`}>
                          {(evaluation.validity * 100).toFixed(0)}%
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Logical Issues */}
            {result.result_content?.logical_issues && result.result_content.logical_issues.length > 0 && (
              <div className="mt-3">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  ⚠️ Logical Issues:
                </div>
                <ul className="space-y-1">
                  {result.result_content.logical_issues.map((issue: string, index: number) => (
                    <li key={index} className="text-sm text-red-700 p-2 bg-red-50 rounded border border-red-200">
                      {issue}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Recommendations */}
            {result.result_content?.recommendations && result.result_content.recommendations.length > 0 && (
              <div className="mt-3">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  💡 Recommendations:
                </div>
                <ul className="space-y-1">
                  {result.result_content.recommendations.map((recommendation: string, index: number) => (
                    <li key={index} className="text-sm text-blue-700 p-2 bg-blue-50 rounded border border-blue-200">
                      {recommendation}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  const renderFormalizerResults = (results: AgentResult[]) => {
    return (
      <div className="space-y-3">
        {results.map((result, index) => (
          <div key={index} className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
            <div className="flex justify-between items-start mb-2">
              <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                📸 Snapshot {result.snapshot_id}
              </span>
              <span className="text-xs text-gray-500">
                {new Date(result.processed_at * 1000).toLocaleTimeString()}
              </span>
            </div>
            <div className="flex justify-between items-start mb-3">
              <span className="font-medium text-green-700 flex items-center">
                <span className="mr-2">📐</span>
                Formalization Agent
              </span>
              <span className="text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded">
                {result.confidence.toFixed(2)} confidence
              </span>
            </div>
            {result.result_content?.definitions && (
              <div className="mt-3 space-y-2">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  📚 Definitions:
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                  {result.result_content.definitions.predicates.length > 0 && (
                    <div className="p-2 bg-blue-50 rounded border border-blue-200">
                      <div className="text-sm font-medium text-blue-700 mb-2">Predicates:</div>
                      <div className="space-y-1">
                        {result.result_content.definitions.predicates.map((pred: any) => (
                          <div key={pred.symbol} className="text-sm">
                            <span className="font-mono text-blue-800">{pred.symbol}</span>
                            <span className="text-gray-600"> = </span>
                            <span className="text-gray-700">{pred.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {result.result_content.definitions.constants.length > 0 && (
                    <div className="p-2 bg-purple-50 rounded border border-purple-200">
                      <div className="text-sm font-medium text-purple-700 mb-2">Constants:</div>
                      <div className="space-y-1">
                        {result.result_content.definitions.constants.map((constDef: any) => (
                          <div key={constDef.symbol} className="text-sm">
                            <span className="font-mono text-purple-800">{constDef.symbol}</span>
                            <span className="text-gray-600"> = </span>
                            <span className="text-gray-700">{constDef.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}
            {result.result_content?.formalizations && result.result_content.formalizations.length > 0 && (
              <div className="mt-3 space-y-2">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  📐 Formalizations:
                </div>
                <div className="space-y-2">
                  {result.result_content.formalizations.map((formalization: any, fIndex: number) => (
                    <div key={fIndex} className="p-2 bg-green-50 rounded border border-green-200">
                      <div className="flex justify-between items-start">
                        <span className="text-sm font-medium text-gray-700">
                          Step {formalization.symbol}:
                        </span>
                        <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                          ASCII
                        </span>
                      </div>
                      <div className="text-sm font-mono text-gray-800 mt-1">
                        {formalization.ascii}
                      </div>
                      {formalization.json_structure && Object.keys(formalization.json_structure).length > 0 && (
                        <div className="mt-2">
                          <div className="text-xs text-gray-500 mb-1">JSON Structure:</div>
                          <div className="text-xs font-mono text-gray-700 bg-white p-2 rounded border overflow-x-auto">
                            <pre className="whitespace-pre-wrap">{JSON.stringify(formalization.json_structure, null, 2)}</pre>
                          </div>
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        ))}
      </div>
    )
  }

  const renderImprovementResults = (results: AgentResult[]) => {

    // Get current conversation state to find the concluding proposition
    const { conversation } = getCurrentConversationState()
    const currentSnapshot = conversation.snapshots[conversation.snapshots.length - 1]
    const concludingProposition = currentSnapshot.argument.length > 0 
      ? currentSnapshot.argument[currentSnapshot.argument.length - 1] 
      : null

    const handleAcceptRecommendation = (recommendationId: string) => {
      setAcceptedRecommendations(prev => new Set([...prev, recommendationId]))
      setRejectedRecommendations(prev => {
        const newSet = new Set(prev)
        newSet.delete(recommendationId)
        return newSet
      })
    }

    const handleRejectRecommendation = (recommendationId: string) => {
      setRejectedRecommendations(prev => new Set([...prev, recommendationId]))
      setAcceptedRecommendations(prev => {
        const newSet = new Set(prev)
        newSet.delete(recommendationId)
        return newSet
      })
    }

    const getImpactColor = (impact: string) => {
      switch (impact) {
        case 'high': return 'bg-red-100 text-red-800 border-red-200'
        case 'medium': return 'bg-yellow-100 text-yellow-800 border-yellow-200'
        case 'low': return 'bg-green-100 text-green-800 border-green-200'
        default: return 'bg-gray-100 text-gray-800 border-gray-200'
      }
    }

    const getImpactIcon = (impact: string) => {
      switch (impact) {
        case 'high': return '🔥'
        case 'medium': return '⚡'
        case 'low': return '💡'
        default: return '📈'
      }
    }

    const getTypeIcon = (type: string) => {
      switch (type) {
        case 'new': return '✨'
        case 'rewrite': return '✏️'
        default: return '📝'
      }
    }

    const getPlacementIcon = (placement: string) => {
      switch (placement) {
        case 'assumption': return '🏗️'
        case 'argument': return '🔗'
        default: return '📋'
      }
    }

    const renderRecommendation = (recommendation: any) => {
      const isAccepted = acceptedRecommendations.has(recommendation.id)
      const isRejected = rejectedRecommendations.has(recommendation.id)
      const isProcessed = isAccepted || isRejected

      return (
        <div 
          key={recommendation.id} 
          className={`p-4 rounded-lg border shadow-sm transition-all duration-200 ${
            isAccepted ? 'bg-green-50 border-green-200' :
            isRejected ? 'bg-red-50 border-red-200' :
            'bg-white border-gray-200 hover:border-blue-300'
          }`}
        >
          {/* Recommendation Header */}
          <div className="flex justify-between items-start mb-3">
            <div className="flex items-center space-x-2">
              <span className="text-lg">🎯</span>
              <span className="font-medium text-gray-800">Recommendation {recommendation.id}</span>
              <span className={`px-2 py-1 rounded text-xs font-medium border ${getImpactColor(recommendation.impact)}`}>
                {getImpactIcon(recommendation.impact)} {recommendation.impact.toUpperCase()} IMPACT
              </span>
            </div>
            <div className="flex items-center space-x-2">
              {isProcessed && (
                <span className={`px-2 py-1 rounded text-xs font-medium ${
                  isAccepted ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                }`}>
                  {isAccepted ? '✅ ACCEPTED' : '❌ REJECTED'}
                </span>
              )}
            </div>
          </div>

          {/* Reasoning */}
          <div className="text-sm text-gray-700 mb-4 p-3 bg-gray-50 rounded border">
            <span className="font-medium text-gray-600">💭 Reasoning:</span> {recommendation.reasoning}
          </div>

          {/* Target Proposition */}
          <div className="mb-4">
            <div className="text-sm font-medium text-gray-700 mb-2 flex items-center">
              <span className="mr-2">🎯</span>
              Target Proposition: <span className="font-mono text-blue-600 ml-1">{recommendation.target_proposition}</span>
            </div>
            {concludingProposition && (
              <div className="text-sm text-gray-600 p-2 bg-blue-50 rounded border border-blue-200">
                <span className="font-medium">Concluding Proposition:</span> {concludingProposition.proposition}
              </div>
            )}
          </div>

          {/* Expected Conclusion Improvements */}
          <div className="mb-4">
            <div className="text-sm font-medium text-gray-700 mb-2 flex items-center">
              <span className="mr-2">📈</span>
              Expected Conclusion Score Improvements:
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div className="p-2 bg-green-50 rounded border border-green-200">
                <div className="text-xs text-green-600 font-medium">Truth Score</div>
                <div className="text-sm font-mono text-green-800">
                  {recommendation.expected_conclusion_improvement.truth_score_improvement}
                </div>
              </div>
              <div className="p-2 bg-blue-50 rounded border border-blue-200">
                <div className="text-xs text-blue-600 font-medium">Content Validity</div>
                <div className="text-sm font-mono text-blue-800">
                  {recommendation.expected_conclusion_improvement.content_validity_improvement}
                </div>
              </div>
              <div className="p-2 bg-purple-50 rounded border border-purple-200">
                <div className="text-xs text-purple-600 font-medium">Formal Validity</div>
                <div className="text-sm font-mono text-purple-800">
                  {recommendation.expected_conclusion_improvement.formal_validity_improvement}
                </div>
              </div>
            </div>
            <div className="text-xs text-gray-600 mt-2 p-2 bg-gray-50 rounded">
              <span className="font-medium">Improvement Reasoning:</span> {recommendation.expected_conclusion_improvement.reasoning}
            </div>
          </div>

          {/* Propositions in Recommendation Set */}
          <div className="mb-4">
            <div className="text-sm font-medium text-gray-700 mb-2 flex items-center">
              <span className="mr-2">🔗</span>
              Propositions in This Recommendation Set:
            </div>
            <div className="space-y-2">
              {recommendation.propositions.map((prop: any, propIndex: number) => (
                <div key={propIndex} className="p-3 bg-gray-50 rounded border border-gray-200">
                  <div className="flex items-start justify-between mb-2">
                    <div className="flex items-center space-x-2">
                      <span className="text-sm">{getTypeIcon(prop.type)}</span>
                      <span className="text-sm">{getPlacementIcon(prop.placement)}</span>
                      <span className="text-sm font-medium text-gray-700">
                        {prop.type === 'rewrite' ? 'Rewrite' : 'New'} Proposition
                      </span>
                      {prop.symbol && (
                        <span className="text-xs bg-gray-200 text-gray-700 px-2 py-1 rounded font-mono">
                          {prop.symbol}
                        </span>
                      )}
                    </div>
                    <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                      {prop.placement}
                    </span>
                  </div>
                  
                  <div className="text-sm text-gray-800 mb-2">
                    {prop.proposition}
                  </div>

                  {prop.type === 'rewrite' && prop.original_proposition && (
                    <div className="text-xs text-gray-600 mb-2 p-2 bg-yellow-50 rounded border border-yellow-200">
                      <span className="font-medium">Original:</span> {prop.original_proposition}
                    </div>
                  )}

                  {prop.justification_suggestions && prop.justification_suggestions.length > 0 && (
                    <div className="text-xs">
                      <span className="font-medium text-gray-600">💡 Justification Suggestions:</span>
                      <ul className="mt-1 space-y-1">
                        {prop.justification_suggestions.map((suggestion: string, suggIndex: number) => (
                          <li key={suggIndex} className="text-gray-600 pl-2">
                            • {suggestion}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>

          {/* Action Buttons */}
          {!isProcessed && (
            <div className="flex justify-end space-x-2 pt-3 border-t border-gray-200">
              <button
                onClick={() => handleRejectRecommendation(recommendation.id)}
                className="px-4 py-2 text-sm font-medium text-red-700 bg-red-50 border border-red-200 rounded hover:bg-red-100 transition-colors"
              >
                ❌ Reject
              </button>
              <button
                onClick={() => handleAcceptRecommendation(recommendation.id)}
                className="px-4 py-2 text-sm font-medium text-green-700 bg-green-50 border border-green-200 rounded hover:bg-green-100 transition-colors"
              >
                ✅ Accept
              </button>
            </div>
          )}

          {isProcessed && (
            <div className="pt-3 border-t border-gray-200">
              <div className="text-sm text-gray-600">
                {isAccepted ? (
                  <span className="text-green-700">✅ This recommendation has been accepted and will be applied to strengthen the argument.</span>
                ) : (
                  <span className="text-red-700">❌ This recommendation has been rejected and will not be applied.</span>
                )}
              </div>
            </div>
          )}
        </div>
      )
    }

    return (
      <div className="space-y-3">
        {results.map((result, index) => {
          const recommendations = result.result_content?.recommendations || []
          
          if (recommendations.length === 0) {
            return null
          }

          return (
            <div key={index} className="p-4 bg-white rounded-lg border border-gray-200 shadow-sm">
              {/* Result Header */}
              <div className="flex justify-between items-start mb-2">
                <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded">
                  📸 Snapshot {result.snapshot_id}
                </span>
                <span className="text-xs text-gray-500">
                  {new Date(result.processed_at * 1000).toLocaleTimeString()}
                </span>
              </div>
              
              <div className="flex justify-between items-start mb-3">
                <span className="font-medium text-indigo-700 flex items-center">
                  <span className="mr-2">🎯</span>
                  Improvement Agent
                </span>
                <span className="text-sm text-gray-500 bg-gray-100 px-2 py-1 rounded">
                  {result.confidence.toFixed(2)} confidence
                </span>
              </div>

              <div className="text-sm text-gray-700 mb-4 p-2 bg-gray-50 rounded">
                💭 {result.reasoning}
              </div>

              {/* Recommendations */}
              <div className="space-y-4">
                <div className="text-sm font-medium text-gray-700 mb-2">
                  🎯 Improvement Recommendations ({recommendations.length}):
                </div>
                {recommendations.map((recommendation: any) => 
                  renderRecommendation(recommendation)
                )}
              </div>
            </div>
          )
        })}
      </div>
    )
  }

  return (
    <div className="mt-4 space-y-6">
      {/* Formalization Status */}
      {allFormalizationsEndorsed && (
        <div className="p-4 bg-green-50 rounded-lg border border-green-200">
          <div className="flex items-center">
            <span className="text-green-700 mr-2">✅</span>
            <span className="text-green-800 font-medium">All formalizations endorsed</span>
          </div>
          <p className="text-green-700 text-sm mt-2">
            Formal evaluation will be triggered automatically when all formalizations are endorsed.
          </p>
        </div>
      )}
      {error && (
        <div className="text-red-600 mb-2 p-2 bg-red-50 rounded border border-red-200">
          Error loading results: {error}
        </div>
      )}

      {/* Show loading state when no results yet and we're actively polling */}
      {!error && currentPollingSnapshotRef.current >= 0 && !tasksCompleteRef.current && activeTaskCount > 0 && (
        <div className="p-4 bg-blue-50 rounded-lg border border-blue-200">
          <div className="text-center">
            <div className="flex items-center justify-center mb-3">
              <p className="text-blue-700 font-medium">Processing with AI agents...</p>
            </div>
            {activeTaskCount > 0 && (
              <div className="text-left">
                <p className="text-blue-600 text-sm mb-2">
                  {activeTaskCount} task{activeTaskCount !== 1 ? 's' : ''} currently running:
                </p>
                <div className="space-y-2">
                  {activeTasks.map((task, index) => (
                    <div key={task.task_id || index} className="flex items-center justify-between p-2 bg-white rounded border border-blue-200">
                      <div className="flex items-center">
                        <span className="text-blue-600 mr-2">
                          {task.status === 'running' ? '🔄' : '⏳'}
                        </span>
                        <span className="text-sm text-blue-800">
                          {getAgentDisplayName(task.agent_type)}
                        </span>
                      </div>
                      <span className="text-xs text-blue-600 bg-blue-100 px-2 py-1 rounded">
                        {task.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {Object.keys(resultsByAgent).length > 0 &&
        <h3 className="text-lg font-semibold mb-4 text-gray-800">🤖 Agent Suggestions & Evaluations</h3>
      }

      {/* Show results only if there are any */}
      {Object.keys(resultsByAgent).length > 0 && Object.entries(resultsByAgent).map(([agentType, results]) => (
        <div key={agentType} className="p-4 bg-gray-50 rounded-lg border border-gray-200">
          <h4 className="text-md font-semibold mb-3 text-gray-800">
            {agentType === 'content_evaluator' && '🔍 Content Evaluator'}
            {agentType === 'form_evaluator' && '🧮 Formal Logic Evaluator'}
            {agentType === 'formalizer' && '📐 Formalization Agent'}
            {agentType === 'improver' && '🎯 Improvement Agent'}
          </h4>
          
          {agentType === 'content_evaluator' && renderContentEvaluatorResults(results)}
          {agentType === 'form_evaluator' && renderFormEvaluatorResults(results)}
          {agentType === 'formalizer' && renderFormalizerResults(results)}
          {agentType === 'improver' && renderImprovementResults(results)}
        </div>
      ))}

    </div>
  )
}
