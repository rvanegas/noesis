import ActionMenu from './ActionMenu'

type UserMode = 'waiting' | 'ready' | 'input'

interface ThesisActionsProps {
  thesisType: 'thesis'
  userMode: UserMode
  onArgue: (thesisType: string) => Promise<void>
}

export default function ThesisActions({
  thesisType,
  userMode,
  onArgue
}: ThesisActionsProps) {
  const actionItems = [
    {
      label: 'Argue',
      onClick: async () => {
        await onArgue(thesisType)
      },
      show: true
    }
  ]

  return (
    <ActionMenu
      actionItems={actionItems}
      userMode={userMode}
    />
  )
} 