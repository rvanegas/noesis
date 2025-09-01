
type ArgMode = 'thesis' | 'development'

export type StepType = {
  symbol: string
  proposition: string
  justifiers: string[]
  truth: string
  valid_content?: string  // Content validity score from content evaluation
  valid_formal?: string   // Formal validity score from formal evaluation
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
