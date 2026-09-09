import React from 'react'

const Tabs = ({ defaultValue, value, onValueChange, children, className = '' }) => {
  const [activeTab, setActiveTab] = React.useState(value || defaultValue)
  
  const handleTabChange = (newValue) => {
    setActiveTab(newValue)
    if (onValueChange) {
      onValueChange(newValue)
    }
  }
  
  return (
    <div className={className}>
      {React.Children.map(children, child =>
        React.cloneElement(child, { activeTab, onTabChange: handleTabChange })
      )}
    </div>
  )
}

const TabsList = ({ children, className = '', activeTab, onTabChange }) => (
  <div className={`inline-flex h-10 items-center justify-center rounded-md bg-gray-100 p-1 text-gray-500 ${className}`}>
    {React.Children.map(children, child =>
      React.cloneElement(child, { activeTab, onTabChange })
    )}
  </div>
)

const TabsTrigger = ({ value, children, className = '', activeTab, onTabChange }) => (
  <button
    className={`inline-flex items-center justify-center whitespace-nowrap rounded-sm px-3 py-1.5 text-sm font-medium ring-offset-white transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 ${
      activeTab === value
        ? 'bg-white text-gray-950 shadow-sm'
        : 'text-gray-600 hover:text-gray-900'
    } ${className}`}
    onClick={() => onTabChange(value)}
  >
    {children}
  </button>
)

const TabsContent = ({ value, children, className = '', activeTab }) => {
  if (activeTab !== value) return null
  
  return (
    <div className={`mt-2 ring-offset-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-600 focus-visible:ring-offset-2 ${className}`}>
      {children}
    </div>
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }

