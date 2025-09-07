import { create } from 'zustand'
import { produce } from 'immer'
import type { ConversationType, ConversationSnapshot } from './types'

type ApiOperationInfo = {
  url: string
  data: any
  onSuccess: (responseObject: any) => void
  onFinally?: () => void
  operationName: string
}

export function initialSnapshot(): ConversationSnapshot {
  return {
    assumptions: [],
    argument: [],
    explanation: '',
    argMode: 'thesis',
    file_ids: []
  }
}

interface ConversationState {
  conversations: ConversationType[]
  currentConversationIndex: number
  currentSnapshotIndex: number
  nextConversationId: number
  userMode: 'waiting' | 'ready' | 'input'
  snapshotRenderCount: number
  sessionId: string
  lastFailedOperation: ApiOperationInfo | null
  
  updateCurrentConversation: (conversation: ConversationType) => void
  saveConversationName: (conversationId: number, name: string) => void
  getConversationName: (conversationId: number) => string
  saveAgentResults: (conversationId: number, snapshotIndex: number, agentResults: any) => void
  getAgentResults: (conversationId: number, snapshotIndex: number) => { [agentType: string]: any[] }
  setCurrentConversationIndex: (index: number) => void
  setCurrentSnapshotIndex: (index: number) => void
  setUserMode: (mode: 'waiting' | 'ready' | 'input') => void
  incrementSnapshotRenderCount: () => void
  setNextConversationId: (id: number) => void
  setLastFailedOperation: (operation: ApiOperationInfo | null) => void
  getCurrentConversationState: () => { conversation: ConversationType, snapshotIndex: number }
  getCurrentConversationId: () => number
  createConversationFromProposition: (proposition: string) => void
  createConversation: (initPrompt?: string) => void
  applyAgentResults: (changes: {
    truthUpdates?: { symbol: string, value: string }[]
    validityUpdates?: { symbol: string, value: string }[]
    formalizationUpdates?: { symbol: string, formalization: any }[]
    formalValidityUpdates?: { symbol: string, value: string }[]
    formalizationDefinitions?: any
  }) => void
  applyNewArgument: (responseData: any) => void
  constructUpdatedSnapshot: (recommendation: any) => any
}

export const useConversationStore = create<ConversationState>((set, get) => ({
  conversations: [{ id: 1, name: '', initPrompt: undefined, snapshots: [initialSnapshot()] }],
  currentConversationIndex: 0,
  currentSnapshotIndex: 0,
  nextConversationId: 2,
  userMode: 'ready',
  snapshotRenderCount: 0,
  sessionId: crypto.randomUUID(),
  lastFailedOperation: null,

  updateCurrentConversation: (conversation) => {
    set(produce((state) => {
      state.conversations[state.currentConversationIndex] = conversation
    }))
  },

  saveConversationName: (conversationId, name) => {
    set(produce((state) => {
      const conversation = state.conversations.find((c: ConversationType) => c.id === conversationId)
      if (conversation) {
        conversation.name = name
      }
    }))
  },

  getConversationName: (conversationId) => {
    const state = get()
    const conversation = state.conversations.find((c: ConversationType) => c.id === conversationId)
    return conversation?.name || ''
  },

  saveAgentResults: (conversationId: number, snapshotIndex: number, agentResults: { [agentType: string]: any[] }) => {
    set(produce((state) => {
      const conversation = state.conversations.find((c: ConversationType) => c.id === conversationId)
      if (conversation && conversation.snapshots[snapshotIndex]) {
        // Store the raw agent results for the specific snapshot
        conversation.snapshots[snapshotIndex].agentResults = agentResults
      }
    }))
  },

  getAgentResults: (conversationId: number, snapshotIndex: number) => {
    const state = get()
    const conversation = state.conversations.find((c: ConversationType) => c.id === conversationId)
    if (conversation && conversation.snapshots[snapshotIndex]) {
      return conversation.snapshots[snapshotIndex].agentResults || {}
    }
    return {}
  },

  setCurrentConversationIndex: (index) => 
    set(produce((state) => {
      state.currentConversationIndex = index
      // Set currentSnapshotIndex to the last snapshot of the selected conversation
      const conversation = state.conversations[index]
      if (conversation && conversation.snapshots.length > 0) {
        state.currentSnapshotIndex = conversation.snapshots.length - 1
      } else {
        state.currentSnapshotIndex = 0  // Always at least one snapshot
      }
    })),

  setCurrentSnapshotIndex: (index) => 
    set({ currentSnapshotIndex: index }),

  setUserMode: (mode) => 
    set({ userMode: mode }),

  incrementSnapshotRenderCount: () => 
    set(produce((state) => {
      state.snapshotRenderCount++
    })),

  setNextConversationId: (id) => 
    set({ nextConversationId: id }),

  setLastFailedOperation: (operation) => 
    set({ lastFailedOperation: operation }),

  getCurrentConversationState: () => {
    const state = get()
    return {
      conversation: state.conversations[state.currentConversationIndex],
      snapshotIndex: state.currentSnapshotIndex
    }
  },

  getCurrentConversationId: () => {
    const state = get()
    return state.conversations[state.currentConversationIndex].id
  },

  createConversationFromProposition: (proposition: string) => {
    const state = get()
    const newConversation = {
      id: state.nextConversationId,
      name: '',
      initPrompt: proposition,
      snapshots: [initialSnapshot()]
    }
    
    // Use addConversation to ensure consistent behavior
    set(produce((state) => {
      state.conversations.push(newConversation)
      state.currentConversationIndex = state.conversations.length - 1
      state.nextConversationId = newConversation.id + 1
    }))
    set({ currentSnapshotIndex: 0 })
  },

  createConversation: (initPrompt?: string) => {
    const state = get()
    const newConversation = {
      id: state.nextConversationId,
      name: '',
      initPrompt,
      snapshots: [initialSnapshot()]
    }
    set(produce((state) => {
      state.conversations.push(newConversation)
      state.currentConversationIndex = state.conversations.length - 1
      state.nextConversationId = newConversation.id + 1
    }))
    set({ currentSnapshotIndex: 0 })
  },

  applyAgentResults: (changes) => {
    set(produce((state) => {
      const conversation = state.conversations[state.currentConversationIndex]
      if (conversation && conversation.snapshots[state.currentSnapshotIndex]) {
        const currentSnapshot = conversation.snapshots[state.currentSnapshotIndex]
        let hasChanges = false

        // Apply truth updates
        if (changes.truthUpdates) {
          changes.truthUpdates.forEach(({ symbol, value }) => {
            const stepIndex = currentSnapshot.argument.findIndex((s: any) => s.symbol === symbol)
            if (stepIndex !== -1) {
              currentSnapshot.argument[stepIndex].truth_score = value
              hasChanges = true
            }
          })
        }

        // Apply validity updates (content validity)
        if (changes.validityUpdates) {
          changes.validityUpdates.forEach(({ symbol, value }) => {
            const stepIndex = currentSnapshot.argument.findIndex((s: any) => s.symbol === symbol)
            if (stepIndex !== -1) {
              currentSnapshot.argument[stepIndex].content_validity = value
              hasChanges = true
            }
          })
        }

        // Apply formalization updates
        if (changes.formalizationUpdates) {
          changes.formalizationUpdates.forEach(({ symbol, formalization }) => {
            const stepIndex = currentSnapshot.argument.findIndex((s: any) => s.symbol === symbol)
            if (stepIndex !== -1) {
              // Skip if this step already has an endorsed formalization
              if (currentSnapshot.argument[stepIndex].formalization?.endorsed) {
                return
              }
              currentSnapshot.argument[stepIndex].formalization = formalization
              hasChanges = true
            }
          })
        }

        // Apply formal validity updates (to both argument and assumption steps)
        if (changes.formalValidityUpdates) {
          changes.formalValidityUpdates.forEach(({ symbol, value }) => {
            // Check argument steps
            const argStepIndex = currentSnapshot.argument.findIndex((s: any) => s.symbol === symbol)
            if (argStepIndex !== -1) {
              currentSnapshot.argument[argStepIndex].formal_validity = value
              hasChanges = true
            }

            // Check assumption steps
            const assumptionStepIndex = currentSnapshot.assumptions.findIndex((s: any) => s.symbol === symbol)
            if (assumptionStepIndex !== -1) {
              currentSnapshot.assumptions[assumptionStepIndex].formal_validity = value
              hasChanges = true
            }
          })
        }

        // Apply formalization definitions
        if (changes.formalizationDefinitions) {
          currentSnapshot.formalization_definitions = changes.formalizationDefinitions
          hasChanges = true
        }


        // Increment render count if there were changes
        if (hasChanges) {
          state.snapshotRenderCount += 1
        }
      }
    }))
  },

  applyNewArgument: (responseData: any) => {
    set(produce((state) => {
      const conversation = state.conversations[state.currentConversationIndex]
      if (conversation) {
        const currentSnapshot = conversation.snapshots[state.currentSnapshotIndex]
        
        // Create new snapshot with the server's response
        const newSnapshot = {
          ...currentSnapshot,
          ...responseData,
        }
        
        // Remove snapshots after the current index and add the new one
        conversation.snapshots.splice(state.currentSnapshotIndex + 1)
        conversation.snapshots.push(newSnapshot)
        
        // Update the current snapshot index to point to the new snapshot
        state.currentSnapshotIndex = conversation.snapshots.length - 1
        
        // Increment render count to trigger re-renders
        state.snapshotRenderCount += 1
      }
    }))
  },

  constructUpdatedSnapshot: (recommendation) => {
    const state = get()
    const conversation = state.conversations[state.currentConversationIndex]
    if (!conversation) return null

    const currentSnapshot = conversation.snapshots[state.currentSnapshotIndex]
    
    // Use Immer to create updated snapshot with proper deep copy
    const updatedSnapshot = produce(currentSnapshot, (draft) => {
      // Apply both new propositions and rewrites
      recommendation.propositions.forEach((prop: any) => {
        if (prop.type === 'new') {
          // Add new proposition
          // Generate next available single letter symbol
          const existingSymbols = new Set([
            ...draft.argument.map(s => s.symbol),
            ...draft.assumptions.map(s => s.symbol)
          ])
          
          let nextSymbol = 'A'
          while (existingSymbols.has(nextSymbol)) {
            nextSymbol = String.fromCharCode(nextSymbol.charCodeAt(0) + 1)
          }
          
          const newStep = {
            symbol: nextSymbol,
            proposition: prop.proposition,
            justifiers: prop.justifies_symbol ? [prop.justifies_symbol] : [],
            truth_score: '',
            content_validity: undefined,
            formal_validity: undefined,
            formalization: undefined
          }
          
          if (prop.placement === 'assumption') {
            draft.assumptions.push(newStep)
          } else {
            draft.argument.push(newStep)
          }
        } else if (prop.type === 'rewrite' && prop.symbol) {
          // Apply proposition rewrites
          // Check argument steps
          const argStepIndex = draft.argument.findIndex((s: any) => s.symbol === prop.symbol)
          if (argStepIndex !== -1) {
            draft.argument[argStepIndex].proposition = prop.proposition
          }
          
          // Check assumption steps
          const assumptionStepIndex = draft.assumptions.findIndex((s: any) => s.symbol === prop.symbol)
          if (assumptionStepIndex !== -1) {
            draft.assumptions[assumptionStepIndex].proposition = prop.proposition
          }
        }
      })
    })
    
    return updatedSnapshot
  }
}))
