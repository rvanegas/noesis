import './App.css'

import {useEffect, useRef} from 'react'

import type {StepType, FileType} from './types'
import {exportMarkdown} from './markdown'
import {useConversationState, useConversationActions, useConversationNavigation} from './ConversationHooks'
import {useConversationStore} from './conversationStore'
import PropositionActions from './PropositionActions'
import AllAgentResults from './AllAgentResults'


const bigButtonClassNames = `bg-indigo-600 hover:bg-indigo-500
  text-white font-bold px-4 py-2 rounded-md`

// Reusable FlexTable component
const FlexTable = ({ children }: { children: React.ReactNode }) => (
  <div className="flex flex-col">
    {children}
  </div>
)

const FlexRow = ({ 
  label, 
  children, 
  chevron 
}: { 
  label?: string
  children?: React.ReactNode
  chevron?: React.ReactNode
}) => (
  <div className="flex flex-col">
    <div className="flex">
      <div className="w-[20px] flex-shrink-0">{chevron}</div>
      <div className={label ? "text-lg font-bold text-left" : "text-left"}>{label || children}</div>
    </div>
  </div>
)

// Section wrapper component
const Section = ({ children }: { children: React.ReactNode }) => (
  <div className="mb-2">
    {children}
  </div>
)

function Conversation({
  files
}: {
  files: FileType[]
}) {
  const { conversations, currentConversationIndex, currentSnapshotIndex, 
    userMode, setUserMode } = useConversationStore()
  const conversation = conversations[currentConversationIndex]
  const currentSnapshot = conversation.snapshots[currentSnapshotIndex]

  const {
    targetLoc,
    setTargetLoc,
    targetIndex,
    setTargetIndex,
    inputText,
    setInputText,
    copied,
    setCopied,
    inputRef,
  } = useConversationState()

  const {
    handleThesis,
    handleUserJustify,
    handleAction,
    handleEndorseFormalization,
    handleRejectFormalization,
    handleDispute,
    retryLastOperation,
    lastFailedOperation
  } = useConversationActions(
    setInputText,
    targetLoc,
    targetIndex
  )

  const {
    handleUndo,
    handleRedo
  } = useConversationNavigation()

  const handleCopy = async () => {
    const text = exportMarkdown(currentSnapshot)
    await navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 3000)
  }

  const bottomRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => {
    if (userMode == 'waiting') {
      bottomRef.current?.scrollIntoView({behavior: 'smooth'})
    }
    
    if (inputRef.current && (userMode == 'ready' || userMode == 'input')) {
      inputRef.current.focus()
    }
  }, [userMode])

  const hasCalledTheses = useRef(false)
  useEffect(() => {
    if (currentSnapshotIndex == 0 && !hasCalledTheses.current && conversation.initPrompt) {
      hasCalledTheses.current = true
      handleThesis(conversation.initPrompt)
    }
  }, [currentSnapshotIndex])

  const loadingIndicator = userMode == 'waiting' && (
    <div className="mt-2 flex items-center space-x-4">
      <span className="text-sm text-zinc-400 italic">
        {userMode == 'waiting' ? 'Dianoia is thinking' : 'Dianoia is evaluating scores'}
      </span>
      <span className="typing-indicator">
        <span className="typing-dot"></span>
        <span className="typing-dot"></span>
        <span className="typing-dot"></span>
      </span>
    </div>
  )

  const retryButton = lastFailedOperation ? (
    <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-lg">
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <p className="text-sm text-red-800 font-medium">
            Operation failed: {lastFailedOperation.operationName}
          </p>
          <p className="text-xs text-red-600 mt-1">
            The AI service encountered an error. You can retry this operation.
          </p>
        </div>
        <button
          onClick={retryLastOperation}
          disabled={userMode === 'waiting'}
          className={`ml-4 px-4 py-2 bg-red-600 hover:bg-red-700 disabled:bg-red-400
            text-white text-sm font-medium rounded-md transition-colors`}>
          {userMode === 'waiting' ? 'Retrying...' : 'Retry'}
        </button>
      </div>
    </div>
  ) : undefined

  const argumentNode = (loc: string, argument: StepType[]) => {
    const argumentSteps = argument.map((step, step_index) => {
      const actions = (
        <PropositionActions
          step={step}
          stepIndex={step_index}
          loc={loc}
          argumentLength={argument.length}
          userMode={userMode}

          onUserJustify={(loc, stepIndex) => {
            setUserMode('input')
            setTargetLoc(loc)
            setTargetIndex(stepIndex)
          }}
          onAssume={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
          onRemove={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
          onDispute={handleDispute}
          onExplain={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
          onEndorseFormalization={(loc, stepIndex) => handleEndorseFormalization(loc, stepIndex)}
          onRejectFormalization={(loc, stepIndex) => handleRejectFormalization(loc, stepIndex)}

          setUserMode={setUserMode}
          setTargetLoc={setTargetLoc}
          setTargetIndex={setTargetIndex}
        />
      )

      const justifierSpan = () => {
        let justifier = step.justifiers.length == 0 ? 'premise' : step.justifiers.join(', ')
        return <span>[{justifier}]</span>
      }

      // Display agent result values
      const agentValuesDisplay = () => {
        const hasTruth = step.truth_score && step.truth_score !== ""
        const hasContentValidity = step.content_validity && step.content_validity !== "" && step.justifiers.length > 0
        const hasFormalValidity = step.formal_validity && step.formal_validity !== "" && step.justifiers.length > 0
        const hasFormalization = step.formalization

        if (!hasTruth && !hasContentValidity && !hasFormalValidity && !hasFormalization) {
          return null
        }
        return (
          <div className="mt-2 ml-4 space-y-1">
            {/* Truth and Validity Values */}
            {(hasTruth || hasContentValidity || hasFormalValidity) && (
              <div className="flex gap-2 text-xs">
                {hasTruth && (
                  <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded">
                    Truth: {(parseFloat(step.truth_score) * 100).toFixed(0)}%
                  </span>
                )}
                {hasContentValidity && (
                  <span className="px-2 py-1 bg-green-100 text-green-800 rounded">
                    Content Validity: {(parseFloat(step.content_validity!) * 100).toFixed(0)}%
                  </span>
                )}
                {hasFormalValidity && (
                  <span className="px-2 py-1 bg-orange-100 text-orange-800 rounded">
                    Formal Validity: {(parseFloat(step.formal_validity!) * 100).toFixed(0)}%
                  </span>
                )}
              </div>
            )}
            
            {/* Formalization */}
            {hasFormalization && step.formalization && (
              <div className="text-xs">
                <div className={`px-2 py-1 rounded font-mono flex items-center gap-2 ${
                  step.formalization.endorsed 
                    ? 'bg-green-100 text-green-800 border border-green-300' 
                    : 'bg-purple-100 text-purple-800 border border-purple-300'
                }`}>
                  <span>{step.formalization.ascii}</span>
                  {step.formalization.endorsed && (
                    <span className="text-green-600">✓</span>
                  )}
                </div>
              </div>
            )}
          </div>
        )
      }

      return (
        <div key={step_index}>
          <FlexRow chevron={actions}>
            ({step.symbol}) {step.proposition} {justifierSpan()}
          </FlexRow>
          {agentValuesDisplay()}
        </div>
      )
    })
    return <div>{argumentSteps}</div>
  }

  // Get formalization definitions from snapshot
  const getFormalizationDefinitions = () => {
    if (!currentSnapshot.formalization_definitions) {
      return null
    }

    return (
      <div className="mt-4 p-3 bg-gray-50 rounded-lg border border-gray-200">
        <div className="text-sm font-medium text-gray-700 mb-2">
          📚 Formal Logic Definitions:
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {currentSnapshot.formalization_definitions.predicates && currentSnapshot.formalization_definitions.predicates.length > 0 && (
            <div className="p-2 bg-blue-50 rounded border border-blue-200">
              <div className="text-sm font-medium text-blue-700 mb-2">Predicates:</div>
              <div className="space-y-1">
                {currentSnapshot.formalization_definitions.predicates.map((pred: any) => (
                  <div key={pred.symbol} className="text-sm">
                    <span className="font-mono text-blue-800">{pred.symbol}</span>
                    <span className="text-gray-600"> = </span>
                    <span className="text-gray-700">{pred.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
          {currentSnapshot.formalization_definitions.constants && currentSnapshot.formalization_definitions.constants.length > 0 && (
            <div className="p-2 bg-purple-50 rounded border border-purple-200">
              <div className="text-sm font-medium text-purple-700 mb-2">Constants:</div>
              <div className="space-y-1">
                {currentSnapshot.formalization_definitions.constants.map((constDef: any) => (
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
    )
  }

  const argumentDiv = () => (
    <div>
      {argumentNode('argument', currentSnapshot.argument)}
      {/* Display formalization definitions after the last step */}
      {getFormalizationDefinitions()}
    </div>
  )

  const assumptionsDiv = (
    <div>
      {currentSnapshot.assumptions.map((step, step_index) => {
        const actions = (
          <PropositionActions
            step={step}
            stepIndex={step_index}
            loc="assumptions"
            argumentLength={currentSnapshot.assumptions.length}
            userMode={userMode}

            onUserJustify={(loc, stepIndex) => {
              setUserMode('input')
              setTargetLoc(loc)
              setTargetIndex(stepIndex)
            }}
            onAssume={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
            onRemove={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
            onDispute={handleDispute}
            onExplain={(action, loc, stepIndex, errorLabel) => handleAction(action, loc, stepIndex, errorLabel)}
            onEndorseFormalization={(loc, stepIndex) => handleEndorseFormalization(loc, stepIndex)}
            onRejectFormalization={(loc, stepIndex) => handleRejectFormalization(loc, stepIndex)}

            setUserMode={setUserMode}
            setTargetLoc={setTargetLoc}
            setTargetIndex={setTargetIndex}
          />
        )

        // Display agent result values for assumptions
        const agentValuesDisplay = () => {
                  // Assumptions always have truth=1.0 and are never evaluated by agents
        const hasTruth = step.truth_score && step.truth_score !== ""
        const hasContentValidity = step.content_validity && step.content_validity !== "" && step.justifiers.length > 0
        const hasFormalValidity = step.formal_validity && step.formal_validity !== "" && step.justifiers.length > 0
          const hasFormalization = step.formalization

          if (!hasTruth && !hasContentValidity && !hasFormalValidity && !hasFormalization) {
            return null
          }

          return (
            <div className="mt-2 ml-4 space-y-1">
              {/* Truth and Validity Values */}
              {(hasTruth || hasContentValidity || hasFormalValidity) && (
                <div className="flex gap-2 text-xs">
                  {hasTruth && (
                    <span className="px-2 py-1 bg-blue-100 text-blue-800 rounded">
                      Truth: {(parseFloat(step.truth_score) * 100).toFixed(0)}% (Assumed)
                    </span>
                  )}
                  {hasContentValidity && (
                    <span className="px-2 py-1 bg-green-100 text-green-800 rounded">
                      Content Validity: {(parseFloat(step.content_validity!) * 100).toFixed(0)}%
                    </span>
                  )}
                  {hasFormalValidity && (
                    <span className="px-2 py-1 bg-orange-100 text-orange-800 rounded">
                      Formal Validity: {(parseFloat(step.formal_validity!) * 100).toFixed(0)}%
                    </span>
                  )}
                </div>
              )}
              
              {/* Formalization */}
              {hasFormalization && step.formalization && (
                <div className="text-xs">
                  <div className={`px-2 py-1 rounded font-mono flex items-center gap-2 ${
                    step.formalization.endorsed 
                      ? 'bg-green-100 text-green-800 border border-green-300' 
                      : 'bg-purple-100 text-purple-800 border border-purple-300'
                  }`}>
                    <span>{step.formalization.ascii}</span>
                    {step.formalization.endorsed && (
                      <span className="text-green-600">✓</span>
                    )}
                  </div>
                </div>
              )}
            </div>
          )
        }

        return (
          <div key={step_index}>
            <FlexRow chevron={actions}>
              ({step.symbol}) {step.proposition}
            </FlexRow>
            {agentValuesDisplay()}
          </div>
        )
      })}
    </div>
  )


  const explanationDiv = () => {
    return (
      <FlexRow>{currentSnapshot.explanation}</FlexRow>
    )
  }

  const snapshotId = currentSnapshotIndex < 1 ? '' : `.${currentSnapshotIndex}`

  const renderAssociatedFileNames = () => (
    <div>
      {currentSnapshot.file_ids.map(file_id => {
        const file = files.find(f => f.file_id === file_id)
        return (
          <span 
            key={file_id} 
            className="inline-block bg-gray-200 dark:bg-gray-700 px-2 py-1 rounded mr-2 mb-1 text-sm"
          >
            {file ? file.filename : file_id}
          </span>
        )
      })}
    </div>
  )

  const messagesDiv = (
    <div className="flex flex-1 overflow-y-auto p-5 flex-col w-[100%] scroll-hide">
      <FlexTable>
        <Section>
          <FlexRow label="Id:" />
          <FlexRow>{conversation.id}{snapshotId}</FlexRow>
        </Section>
        {currentSnapshot.file_ids && currentSnapshot.file_ids.length > 0 && (
          <Section>
            <FlexRow label="Files:" />
            <FlexRow>{renderAssociatedFileNames()}</FlexRow>
          </Section>
        )}

        {currentSnapshot.assumptions.length > 0 && (
          <Section>
            <FlexRow label="Assumptions:" />
            {assumptionsDiv}
          </Section>
        )}
        {currentSnapshot.argument.length > 0 && (
          <Section>
            <FlexRow label="Argument:" />
            {argumentDiv()}
          </Section>
        )}
        {currentSnapshot.explanation && (
          <Section>
            <FlexRow label="Explanation:" />
            {explanationDiv()}
          </Section>
        )}
      </FlexTable>
      <AllAgentResults />
      {loadingIndicator}
      {retryButton}
    </div>
  )

  const placeholderText =
    currentSnapshot.argMode == 'thesis' ? 'Enter thesis' :
    userMode == 'input' ? 'Enter proposition' : ''

  const handleEnter = (prompt: string) => {
    if (currentSnapshot.argMode == 'thesis') {
      handleThesis(prompt)
    }
    else if (userMode == 'input') {
      handleUserJustify(prompt)
    }
    setInputText('')
  }

  const userDiv = (
    <div className="p-4 flex gap-2 w-[100%] flex-wrap">
      <input
        ref={inputRef}
        className="flex-1 px-4 bg-slate-200 rounded-full focus:outline-2 focus:outline-indigo-500 dark:bg-zinc-800 "
        value={inputText}
        disabled={!(currentSnapshot.argMode == 'thesis' || userMode == 'input')}
        onChange={e => setInputText(e.target.value)}
        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => {
          if (e.key == 'Enter') {
            handleEnter(inputText)
            e.preventDefault()
          }
        }}
        placeholder={placeholderText}
        tabIndex={1}
      />
      <button
        className={bigButtonClassNames}
        disabled={!(currentSnapshot.argMode == 'thesis' || userMode == 'input')}
        onClick={() => handleEnter(inputText)}
        tabIndex={2}>
        Enter
      </button>
    </div>
  )

  return (
    <>
      {conversation.snapshots.length < 2 ? undefined :
        <div className="fixed top-4 right-4 z-10 flex gap-2">
          <button
            disabled={currentSnapshotIndex <= 0 || userMode == 'waiting'}
            onClick={handleUndo}
            className={bigButtonClassNames + ' disabled:bg-slate-200 dark:disabled:bg-zinc-800'}>
              Undo
          </button>
          <button
            disabled={currentSnapshotIndex >= conversation.snapshots.length - 1
              || userMode == 'waiting'}
            onClick={handleRedo}
            className={bigButtonClassNames + ' disabled:bg-slate-200 dark:disabled:bg-zinc-800'}>
              Redo
          </button>
          <button
            onClick={handleCopy}
            className={bigButtonClassNames}>
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      }
      {messagesDiv}
      {userDiv}
    </>
  )
}

export default Conversation
