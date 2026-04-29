import ActionMenu from './ActionMenu'

type ActionType = 'remove' | 'assume' | 'explain' | 'endorse-formalization'
type UserMode = 'waiting' | 'ready' | 'input'

interface PropositionActionsProps {
  step: any
  stepIndex: number
  loc: string
  argumentLength: number
  userMode: UserMode
  onUserJustify: (loc: string, stepIndex: number) => void
  onAssume: (action: ActionType, loc: string, stepIndex: number, errorLabel: string) => Promise<void>
  onRemove: (action: ActionType, loc: string, stepIndex: number, errorLabel: string) => Promise<void>
  onDispute: (step: any) => Promise<void>
  onExplain: (action: ActionType, loc: string, stepIndex: number, errorLabel: string) => Promise<void>
  onEndorseFormalization: (loc: string, stepIndex: number) => Promise<void>
  onRejectFormalization: (loc: string, stepIndex: number) => Promise<void>
  setUserMode: (mode: UserMode) => void
  setTargetLoc: (loc: string) => void
  setTargetIndex: (index: number) => void
}

export default function PropositionActions({
  step,
  stepIndex,
  loc,
  argumentLength,
  userMode,
  onAssume,
  onRemove,
  onDispute,
  onExplain,
  onEndorseFormalization,
  onRejectFormalization,
  setUserMode,
  setTargetLoc,
  setTargetIndex
}: PropositionActionsProps) {
  const isLastStep = stepIndex === argumentLength - 1
  const hasJustifiers = step.justifiers.length > 0

  const actionItems = [
    {
      label: 'User Justify',
      onClick: () => {
        setUserMode('input')
        setTargetLoc(loc)
        setTargetIndex(stepIndex)
      },
      show: loc !== 'assumptions'
    },
    {
      label: 'Assume',
      onClick: async () => {
        await onAssume('assume', loc, stepIndex, `Assume proposition (${step.symbol})`)
      },
      show: loc !== 'assumptions' && !isLastStep && !hasJustifiers
    },
    {
      label: 'Remove',
      onClick: async () => {
        await onRemove('remove', loc, stepIndex, `Remove proposition (${step.symbol})`)
      },
      show: loc === 'assumptions' || !isLastStep
    },
    {
      label: 'Dispute',
      onClick: async () => {
        await onDispute(step)
      },
      show: loc === 'assumptions' || !isLastStep
    },
    {
      label: 'Explain',
      onClick: async () => {
        await onExplain('explain', loc, stepIndex, `Explain inference to proposition (${step.symbol})`)
      },
      show: loc !== 'assumptions' && hasJustifiers
    },
    {
      label: 'Endorse Formalization',
      onClick: async () => {
        await onEndorseFormalization(loc, stepIndex)
      },
      show: step.formalization && !step.formalization.endorsed
    },
    {
      label: 'Reject Formalization',
      onClick: async () => {
        await onRejectFormalization(loc, stepIndex)
      },
      show: step.formalization !== undefined
    }
  ]

  return (
    <ActionMenu
      actionItems={actionItems}
      userMode={userMode}
    />
  )
}
