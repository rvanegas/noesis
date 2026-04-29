import { ChevronRight } from 'lucide-react'
import { useState } from 'react'

type UserMode = 'waiting' | 'ready' | 'input'

interface ActionItem {
  label: string
  onClick: () => void | Promise<void>
  show: boolean
}

interface ActionMenuProps {
  actionItems: ActionItem[]
  userMode: UserMode
  className?: string
}

export default function ActionMenu({
  actionItems,
  userMode,
  className = "relative"
}: ActionMenuProps) {
  const [isOpen, setIsOpen] = useState(false)
  const isDisabled = userMode === 'waiting'

  const filteredItems = actionItems.filter(item => item.show)

  if (filteredItems.length === 0) {
    return null
  }

  return (
    <div 
      className={className}
    >
      <button
        disabled={isDisabled}
        onClick={() => setIsOpen(!isOpen)}
        className={`inline-flex items-center justify-center px-1 h-6 disabled:opacity-25 disabled:cursor-not-allowed ${
          isOpen 
            ? 'text-gray-600 bg-gray-100' 
            : 'text-gray-400 hover:text-gray-600 hover:bg-gray-100'
        }`}
      >
        <ChevronRight className={`h-4 w-4 transition-transform ${isOpen ? 'rotate-90' : ''}`} />
      </button>
      
      {isOpen && (
        <div className="ml-5 mt-1 bg-gray-100 dark:bg-gray-700 shadow-sm rounded border border-gray-200 dark:border-gray-600">
          <div className="flex gap-1 p-1">
            {filteredItems.map((item, index) => (
              <button
                key={index}
                onClick={() => {
                  item.onClick()
                  setIsOpen(false)
                }}
                className="px-2 py-1 text-xs text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 whitespace-nowrap rounded"
              >
                {item.label}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
