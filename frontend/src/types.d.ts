
type ArgMode = 'thesis' | 'development'

export type StepType = {
  symbol: string
  proposition: string
  justifiers: string[]
  truth: string
  valid: string
  valid_formal?: string
  formalization?: {
    ascii: string
    json_structure: any
    endorsed: boolean
  }

}

type ConversationSnapshot = {
  argument: StepType[]
  assumptions: StepType[]
  argMode: ArgMode
  // evaluationsPending: boolean // DISABLED: Old evaluation system
  explanation: string | undefined
  file_ids: string[]
  formalization_definitions?: {
    predicates: Array<{symbol: string, value: string}>
    constants: Array<{symbol: string, value: string}>
  }
  agentResults?: { [agentType: string]: any[] }
}

type ConversationType = {
  id: number
  name: string
  initPrompt: string | undefined
  snapshots: ConversationSnapshot[]
}

export type FileType = {
  file_id: string
  filename: string
}
