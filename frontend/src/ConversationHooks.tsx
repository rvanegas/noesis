import { useState, useRef } from 'react'
import axios from 'axios'

import type { StepType, ArgMode } from './types'
import { useConversationStore } from './conversationStore'

type ActionType = 'remove' | 'assume' | 'explain' | 'endorse-formalization'

// Type for API operation information
type ApiOperationInfo = {
  url: string
  data: any
  onSuccess: (responseObject: any) => void
  onFinally?: () => void
  operationName: string
}

const VITE_API_BASE_URL = import.meta.env.VITE_API_BASE_URL

export function useConversationState() {
  // used by input to save which user-justify action was selected
  const [targetLoc, setTargetLoc] = useState<string>('')
  const [targetIndex, setTargetIndex] = useState<number>(0)

  // contents of input element
  const [inputText, setInputText] = useState<string>('')

  // export button
  const [copied, setCopied] = useState<boolean>(false)

  // input reference 
  const inputRef = useRef<HTMLInputElement>(null)


  return {
    targetLoc,
    setTargetLoc,
    targetIndex,
    setTargetIndex,
    inputText,
    setInputText,
    copied,
    setCopied,
    inputRef,
  }
}

export function useConversationActions(
  setInputText: (text: string) => void,
  targetLoc: string,
  targetIndex: number
) {
  const { saveConversationName, sessionId, userMode, setUserMode, currentSnapshotIndex,
    getCurrentConversationId, createConversationFromProposition, lastFailedOperation, 
    setLastFailedOperation, applyNewArgument, getCurrentConversationState } = useConversationStore()
  const conversationId = getCurrentConversationId()
  const currentSnapshot = getCurrentConversationState().conversation.snapshots[currentSnapshotIndex]

  // Reusable error handler
  const handleApiError = (error: any, operationInfo?: ApiOperationInfo) => {
    // Handle HTTP errors (like 422 AssistantResponseError)
    if (error.response?.status === 422 && error.response?.data?.detail) {
      console.log('AssistantResponseError detected:', error.response.data.detail)
      if (operationInfo) {
        setLastFailedOperation(operationInfo)
      }
    }
    // Handle other types of errors (JSON parsing, network, etc.)
    else if (operationInfo) {
      console.log('API Error detected:', error.message)
      setLastFailedOperation(operationInfo)
    }
    
    console.error('Error: ', error)
  }

  // Reusable API call wrapper
  const makeApiCall = async (operationInfo: ApiOperationInfo) => {
    try {
      // Add conversation_id as query parameter (format: session_id:conversation_id)
      const url = new URL(operationInfo.url)
      url.searchParams.set('conversation_id', `${sessionId}:${conversationId}`)
      url.searchParams.set('snapshot_id', String(currentSnapshotIndex + 1))
      
      const response = await axios.post(url.toString(), operationInfo.data)
      
      // Check if response data exists
      if (!response.data || !response.data.reply) {
        throw new Error('Invalid response format: missing reply data')
      }
      
      // Parse JSON response
      let responseObject
      try {
        responseObject = JSON.parse(response.data.reply)
      } catch (parseError) {
        throw new Error(`Invalid JSON response: ${parseError instanceof Error ? parseError.message : 'Unknown parsing error'}`)
      }
      
      // Check if parsed object is valid
      if (!responseObject) {
        throw new Error('Empty response object')
      }
      
      operationInfo.onSuccess(responseObject)
      // Clear any previous failed operation on success
      setLastFailedOperation(null)
      return responseObject
    } catch (error: any) {
      handleApiError(error, operationInfo)
    } finally {
      operationInfo.onFinally?.()
    }
  }

  // Retry function
  const retryLastOperation = async () => {
    if (!lastFailedOperation) return
    
    setUserMode('waiting')
    await makeApiCall(lastFailedOperation)
  }

  const handleThesis = async (content?: string) => {
    if (userMode == 'waiting') return
    if (!(content && content.trim())) return

    setInputText('')
    
    let apiPrompt = {
      ...currentSnapshot,
      proposition: content,
    }
    let url = VITE_API_BASE_URL + '/api/argument/argue'
    const argMode: ArgMode = 'development'
    
    // First API call to create thesis
    const thesisResponseObject = await makeApiCall({
      url, data: apiPrompt, onSuccess: (responseObject) => {
        applyNewArgument({ ...responseObject, argMode })
      }, 
      onFinally: () => setUserMode('ready'), 
      operationName: 'Create Thesis'
    })

    url = VITE_API_BASE_URL + '/api/argument/gen-name'
    apiPrompt = {
      ...currentSnapshot,
      ...thesisResponseObject,
      proposition: content,
    }

    await makeApiCall({
      url, data: apiPrompt, onSuccess: (responseObject) => {
        saveConversationName(getCurrentConversationId(), responseObject.name)
      }, 
      onFinally: () => {}, 
      operationName: 'Generate Name'
    })
  }

  const handleUserJustify = async (proposition: string) => {
    setUserMode('waiting')
    
    const url = VITE_API_BASE_URL + '/api/argument/user-justify'
    const apiPrompt = {
      ...currentSnapshot, 
      loc: targetLoc, index: targetIndex,
      proposition
    }
    
    await makeApiCall({
      url, data: apiPrompt, onSuccess: applyNewArgument, 
      onFinally: () => setUserMode('ready'), 
      operationName: 'User Justify' 
    })
  }

  const handleAction = async (
    action: ActionType, loc: string, index: number, errorLabel: string
  ) => {
    setUserMode('waiting')
    const url = VITE_API_BASE_URL + '/api/argument/' + action
    const apiPrompt = {
      ...currentSnapshot,
      loc, index
    }
    
    await makeApiCall({
      url, data: apiPrompt, onSuccess: applyNewArgument, 
      onFinally: () => setUserMode('ready'), 
      operationName: errorLabel
    })
  }

  const handleEndorseFormalization = async (
    loc: string, index: number
  ) => {
    setUserMode('waiting')
    
    const url = VITE_API_BASE_URL + '/api/argument/endorse-formalization'
    const apiPrompt = {
      ...currentSnapshot,
      loc, index
    }
    
    await makeApiCall({ 
      url, 
      data: apiPrompt, 
      onSuccess: applyNewArgument, 
      onFinally: () => setUserMode('ready'), 
      operationName: 'Endorse formalization' 
    })
  }

  const handleRejectFormalization = async (
    loc: string, index: number
  ) => {
    setUserMode('waiting')
    
    const url = VITE_API_BASE_URL + '/api/argument/reject-formalization'
    // Omit formalization_definitions to avoid biasing the formalizer
    const { formalization_definitions, ...snapshotWithoutDefinitions } = currentSnapshot
    const apiPrompt = {
      ...snapshotWithoutDefinitions,
      loc, index
    }
    
    await makeApiCall({ 
      url, 
      data: apiPrompt, 
      onSuccess: applyNewArgument, 
      onFinally: () => setUserMode('ready'), 
      operationName: 'Reject formalization' 
    })
  }

  const handleDispute = async (step: StepType) => {
    // console.log('handleDispute', step)
    createConversationFromProposition(step.proposition)
  }

  return {
    handleThesis,
    handleUserJustify,
    handleAction,
    handleEndorseFormalization,
    handleRejectFormalization,
    handleDispute,
    retryLastOperation,
    lastFailedOperation
  }
}

export function useConversationNavigation() {
  const { incrementSnapshotRenderCount, currentSnapshotIndex, setCurrentSnapshotIndex, 
    setUserMode, conversations, currentConversationIndex } = useConversationStore()

  const conversation = conversations[currentConversationIndex]

  const handleUndo = () => {
    if (currentSnapshotIndex <= 0) return
    const newIndex = currentSnapshotIndex - 1
    incrementSnapshotRenderCount()
    setCurrentSnapshotIndex(newIndex)
    setUserMode('ready')
  }

  const handleRedo = () => {
    if (currentSnapshotIndex >= conversation.snapshots.length - 1) return
    const newIndex = currentSnapshotIndex + 1
    incrementSnapshotRenderCount()
    setCurrentSnapshotIndex(newIndex)
    setUserMode('ready')
  }

  return {
    handleUndo,
    handleRedo
  }
}
