import React from 'react'

const Select = ({ value, onValueChange, children }) => {
  const [isOpen, setIsOpen] = React.useState(false)
  const [selectedValue, setSelectedValue] = React.useState(value)
  
  const handleValueChange = (newValue) => {
    setSelectedValue(newValue)
    setIsOpen(false)
    if (onValueChange) {
      onValueChange(newValue)
    }
  }
  
  return (
    <div className="relative">
      {React.Children.map(children, child =>
        React.cloneElement(child, { 
          selectedValue, 
          isOpen, 
          setIsOpen, 
          onValueChange: handleValueChange 
        })
      )}
    </div>
  )
}

const SelectTrigger = ({ children, className = '', selectedValue, isOpen, setIsOpen }) => (
  <button
    className={`flex h-10 w-full items-center justify-between rounded-md border border-gray-300 bg-white px-3 py-2 text-sm ring-offset-white placeholder:text-gray-500 focus:outline-none focus:ring-2 focus:ring-blue-600 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50 ${className}`}
    onClick={() => setIsOpen(!isOpen)}
  >
    {children}
  </button>
)

const SelectValue = ({ placeholder, selectedValue }) => (
  <span className="block truncate">
    {selectedValue || placeholder}
  </span>
)

const SelectContent = ({ children, isOpen, onValueChange }) => {
  if (!isOpen) return null
  
  return (
    <div className="absolute top-full left-0 right-0 z-50 mt-1 max-h-60 overflow-auto rounded-md border bg-white py-1 shadow-lg">
      {React.Children.map(children, child =>
        React.cloneElement(child, { onValueChange })
      )}
    </div>
  )
}

const SelectItem = ({ value, children, onValueChange }) => (
  <button
    className="relative flex w-full cursor-pointer select-none items-center py-1.5 px-2 text-sm outline-none hover:bg-gray-100 focus:bg-gray-100"
    onClick={() => onValueChange(value)}
  >
    {children}
  </button>
)

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue }

