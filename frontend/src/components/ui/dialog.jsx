import React from 'react'

const Dialog = ({ open, onOpenChange, children }) => {
  const [isOpen, setIsOpen] = React.useState(open || false)
  
  React.useEffect(() => {
    setIsOpen(open || false)
  }, [open])
  
  const handleOpenChange = (newOpen) => {
    setIsOpen(newOpen)
    if (onOpenChange) {
      onOpenChange(newOpen)
    }
  }
  
  return (
    <>
      {React.Children.map(children, child =>
        React.cloneElement(child, { isOpen, onOpenChange: handleOpenChange })
      )}
    </>
  )
}

const DialogTrigger = ({ children, isOpen, onOpenChange }) => (
  React.cloneElement(children, {
    onClick: () => onOpenChange(true)
  })
)

const DialogContent = ({ children, className = '', isOpen, onOpenChange }) => {
  if (!isOpen) return null
  
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div 
        className="fixed inset-0 bg-black bg-opacity-50" 
        onClick={() => onOpenChange(false)}
      />
      <div className={`relative bg-white rounded-lg shadow-lg max-w-lg w-full mx-4 max-h-[85vh] overflow-y-auto ${className}`}>
        {children}
      </div>
    </div>
  )
}

const DialogHeader = ({ children, className = '' }) => (
  <div className={`flex flex-col space-y-1.5 text-center sm:text-left p-6 pb-2 ${className}`}>
    {children}
  </div>
)

const DialogTitle = ({ children, className = '' }) => (
  <h2 className={`text-lg font-semibold leading-none tracking-tight ${className}`}>
    {children}
  </h2>
)

const DialogDescription = ({ children, className = '' }) => (
  <p className={`text-sm text-gray-600 ${className}`}>
    {children}
  </p>
)

const DialogFooter = ({ children, className = '' }) => (
  <div className={`flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 p-6 pt-2 ${className}`}>
    {children}
  </div>
)

export { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger }

