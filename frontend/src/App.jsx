import React, { useState, useEffect } from 'react'
import { Button } from '@/components/ui/button.jsx'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card.jsx'
import { Badge } from '@/components/ui/badge.jsx'
import { Input } from '@/components/ui/input.jsx'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs.jsx'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select.jsx'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog.jsx'
import { BookOpen, Upload, Search, CheckCircle, XCircle, Info, Trash2, Edit3, ChevronDown, Plus } from 'lucide-react'
import {Download, FileText, Edit, Eye, EyeOff } from 'lucide-react'
import './App.css'

// API base URL for dynamic data (uploads)
const API_BASE_URL = 'http://127.0.0.1:4567/api'

function QuestionCard({ question, showAnswer = false, onToggleAnswer, categories = [], onDeleteQuestion, onChangeCategory, onUpdateQuestion, onAddSecondaryCategory, onRemoveSecondaryCategory, onDuplicateQuestion, canEdit = false }) {
  const [showCategorySelect, setShowCategorySelect] = useState(false)
  const [showDeleteDialog, setShowDeleteDialog] = useState(false)
  const [isEditing, setIsEditing] = useState(false)
  const [editedQuestion, setEditedQuestion] = useState({
    question: question.question,
    answer1: question.answer1,
    answer2: question.answer2,
    answer3: question.answer3,
    answer4: question.answer4,
    correct_answer_id: question.correct_answer_id
  })
  
  const answers = [question.answer1, question.answer2, question.answer3, question.answer4]
  
  const handleCategoryChange = async (newCategory) => {
    if (onChangeCategory) {
      await onChangeCategory(question.id, newCategory)
      setShowCategorySelect(false)
    }
  }

  const handleDelete = async () => {
    if (onDeleteQuestion) {
      await onDeleteQuestion(question.id)
      setShowDeleteDialog(false)
    }
  }

  const handleStartEdit = () => {
    setEditedQuestion({
      question: question.question,
      answer1: question.answer1,
      answer2: question.answer2,
      answer3: question.answer3,
      answer4: question.answer4,
      correct_answer_id: question.correct_answer_id
    })
    setIsEditing(true)
  }

  const handleSaveEdit = async () => {
    if (onUpdateQuestion) {
      await onUpdateQuestion(question.id, editedQuestion)
      setIsEditing(false)
    }
  }

  const handleCancelEdit = () => {
    setEditedQuestion({
      question: question.question,
      answer1: question.answer1,
      answer2: question.answer2,
      answer3: question.answer3,
      answer4: question.answer4,
      correct_answer_id: question.correct_answer_id
    })
    setIsEditing(false)
  }

  const handleAnswerChange = (answerIndex, value) => {
    setEditedQuestion(prev => ({
      ...prev,
      [`answer${answerIndex + 1}`]: value
    }))
  }

  const handleCorrectAnswerChange = (answerIndex) => {
    setEditedQuestion(prev => ({
      ...prev,
      correct_answer_id: answerIndex + 1
    }))
  }
  
  return (
    <Card className="question-card mb-4">
      <CardHeader>
        <div className="flex justify-between items-start">
          <div className="flex flex-wrap items-center gap-2">
            {/* Display multiple category badges with management options */}
            {question.categories ? (
              <>
                {question.categories.map((category, index) => (
                  canEdit && question.source === 'uploaded' && index === 0 ? (
                    <div key={index} className="relative">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowCategorySelect(!showCategorySelect)}
                        className="hebrew-text p-1 h-auto"
                      >
                        <Badge variant="secondary" className="hebrew-text">
                          {category}
                        </Badge>
                        <ChevronDown className="w-3 h-3 mr-1" />
                      </Button>
                      {showCategorySelect && (
                        <div className="absolute top-full left-0 z-10 bg-white border rounded-md shadow-lg min-w-48 max-h-40 overflow-y-auto">
                          {categories.map((cat) => (
                            <button
                              key={cat.name}
                              onClick={() => handleCategoryChange(cat.name)}
                              className="w-full text-right px-3 py-2 hover:bg-gray-100 hebrew-text text-sm"
                            >
                              {cat.name}
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  ) : canEdit && question.source === 'uploaded' && index > 0 ? (
                    <div key={index} className="flex items-center gap-1">
                      <Badge variant="secondary" className="hebrew-text">
                        {category}
                      </Badge>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onRemoveSecondaryCategory && onRemoveSecondaryCategory(question.id, category)}
                        className="text-red-500 hover:text-red-700 p-1 h-auto"
                        title="הסר קטגוריה"
                      >
                        <XCircle className="w-3 h-3" />
                      </Button>
                    </div>
                  ) : (
                    <Badge key={index} variant="secondary" className="hebrew-text mb-2">
                      {category}
                    </Badge>
                  )
                ))}
                {/* Add Category button for multi-category questions */}
                {canEdit && question.source === 'uploaded' && question.categories.length < 3 && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onAddSecondaryCategory && onAddSecondaryCategory(question.id)}
                    className="hebrew-text text-green-600 hover:text-green-700 border-green-300 hover:border-green-400"
                  >
                    <Plus className="w-3 h-3 ml-1" />
                    הוסף קטגוריה
                  </Button>
                )}
              </>
            ) : (
              <>
                {canEdit && question.source === 'uploaded' ? (
                  <div className="relative">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => setShowCategorySelect(!showCategorySelect)}
                      className="hebrew-text p-1 h-auto"
                    >
                      <Badge variant="secondary" className="hebrew-text">
                        {question.category}
                      </Badge>
                      <ChevronDown className="w-3 h-3 mr-1" />
                    </Button>
                    {showCategorySelect && (
                      <div className="absolute top-full left-0 z-10 bg-white border rounded-md shadow-lg min-w-48 max-h-40 overflow-y-auto">
                        {categories.map((cat) => (
                          <button
                            key={cat.name}
                            onClick={() => handleCategoryChange(cat.name)}
                            className="w-full text-right px-3 py-2 hover:bg-gray-100 hebrew-text text-sm"
                          >
                            {cat.name}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ) : (
                  <Badge variant="secondary" className="hebrew-text mb-2">
                    {question.category}
                  </Badge>
                )}
                {/* Add Category button for single-category questions */}
                {canEdit && question.source === 'uploaded' && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onAddSecondaryCategory && onAddSecondaryCategory(question.id)}
                    className="hebrew-text text-green-600 hover:text-green-700 border-green-300 hover:border-green-400"
                  >
                    <Plus className="w-3 h-3 ml-1" />
                    הוסף קטגוריה
                  </Button>
                )}
              </>
            )}
          </div>
          <div className="flex items-center gap-2">
            {question.source === 'uploaded' && (
              <Badge variant="outline" className="hebrew-text mb-2">
                הועלה
              </Badge>
            )}
            {canEdit && question.source === 'uploaded' && !isEditing && (
              <Button variant="ghost" size="sm" onClick={handleStartEdit} className="text-blue-600 hover:text-blue-700 hover:bg-blue-50">
                <Edit3 className="w-4 h-4" />
              </Button>
            )}
            {canEdit && question.source === 'uploaded' && (
              <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
                <DialogTrigger asChild>
                  <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700 hover:bg-red-50">
                    <Trash2 className="w-4 h-4" />
                  </Button>
                </DialogTrigger>
                <DialogContent className="hebrew-text">
                  <DialogHeader>
                    <DialogTitle className="hebrew-text">מחיקת שאלה</DialogTitle>
                    <DialogDescription className="hebrew-text">
                      האם אתה בטוח שברצונך למחוק את השאלה? פעולה זו לא ניתנת לביטול.
                    </DialogDescription>
                  </DialogHeader>
                  <DialogFooter className="gap-2">
                    <Button variant="outline" onClick={() => setShowDeleteDialog(false)} className="hebrew-text">
                      ביטול
                    </Button>
                    <Button variant="destructive" onClick={handleDelete} className="hebrew-text">
                      מחק שאלה
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            )}
          </div>
        </div>
        {isEditing ? (
          <div className="space-y-3">
            <textarea
              value={editedQuestion.question}
              onChange={(e) => setEditedQuestion(prev => ({ ...prev, question: e.target.value }))}
              className="w-full p-3 border rounded-md hebrew-text text-lg leading-relaxed resize-none"
              rows="3"
              placeholder="טקסט השאלה..."
            />
            <div className="flex gap-2">
              <Button onClick={handleSaveEdit} className="hebrew-text">
                שמור שינויים
              </Button>
              <Button variant="outline" onClick={handleCancelEdit} className="hebrew-text">
                ביטול
              </Button>
            </div>
          </div>
        ) : (
          <CardTitle className="hebrew-text text-lg leading-relaxed">
            {question.question}
          </CardTitle>
        )}
      </CardHeader>
      <CardContent>
        <div className="space-y-2">
          {answers.map((answer, index) => (
            <div 
              key={index}
              className={`answer-option p-3 rounded-lg border ${
                showAnswer && (index + 1) === question.correct_answer_id 
                  ? 'bg-green-50 border-green-200 text-green-800' 
                  : 'bg-gray-50 border-gray-200'
              }`}
            >
              {isEditing ? (
                <div className="flex items-center gap-2">
                  <input
                    type="radio"
                    name={`correct-${question.id}`}
                    checked={editedQuestion.correct_answer_id === index + 1}
                    onChange={() => handleCorrectAnswerChange(index)}
                    className="text-green-600"
                  />
                  <span className="font-medium">{index + 1}.</span>
                  <input
                    type="text"
                    value={editedQuestion[`answer${index + 1}`]}
                    onChange={(e) => handleAnswerChange(index, e.target.value)}
                    className="flex-1 p-2 border rounded hebrew-text"
                    placeholder={`תשובה ${index + 1}...`}
                  />
                </div>
              ) : (
                <div className="flex items-center gap-2">
                  <span className="font-medium">{index + 1}.</span>
                  <span className="hebrew-text">{answer}</span>
                  {showAnswer && (index + 1) === question.correct_answer_id && (
                    <CheckCircle className="w-4 h-4 text-green-600 mr-auto" />
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
        {!isEditing && (
          <div className="mt-4 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Button 
                variant="outline" 
                onClick={onToggleAnswer}
                className="hebrew-text"
              >
                {showAnswer ? 'הסתר תשובה' : 'הצג תשובה נכונה'}
              </Button>
              
              {/* Action buttons for uploaded questions */}
              {canEdit && question.source === 'uploaded' && (
                <>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => onDuplicateQuestion && onDuplicateQuestion(question.id)}
                    className="hebrew-text"
                    title="שכפל שאלה"
                  >
                    שכפל שאלה
                  </Button>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={handleStartEdit}
                    className="hebrew-text"
                    title="ערוך שאלה"
                  >
                    <Edit3 className="w-4 h-4" />
                  </Button>
                  <Dialog open={showDeleteDialog} onOpenChange={setShowDeleteDialog}>
                    <DialogTrigger asChild>
                      <Button
                        variant="outline"
                        size="sm"
                        className="text-red-600 hover:text-red-700"
                        title="מחק שאלה"
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </DialogTrigger>
                    <DialogContent className="hebrew-text">
                      <DialogHeader>
                        <DialogTitle>מחיקת שאלה</DialogTitle>
                        <DialogDescription>
                          האם אתה בטוח שברצונך למחוק את השאלה? פעולה זו אינה ניתנת לביטול.
                        </DialogDescription>
                      </DialogHeader>
                      <DialogFooter>
                        <Button variant="outline" onClick={() => setShowDeleteDialog(false)}>
                          ביטול
                        </Button>
                        <Button variant="destructive" onClick={handleDelete}>
                          מחק
                        </Button>
                      </DialogFooter>
                    </DialogContent>
                  </Dialog>
                </>
              )}
            </div>
            
            {/* Performance measures display with multiple values */}
            {(question.accuracy !== undefined || question.distinction !== undefined || 
              question.accuracy_list?.length > 0 || question.distinction_list?.length > 0) && (
              <div className="flex items-center gap-4 text-sm text-gray-600">
                {(question.accuracy_list?.length > 0 || question.accuracy !== undefined) && (
                  <div className="flex items-center gap-1">
                    <span className="hebrew-text font-medium">דיוק:</span>
                    <span>
                      {question.accuracy_list?.length > 0 
                        ? question.accuracy_list.map(v => `${v}%`).join(', ')
                        : (question.accuracy != null ? `${question.accuracy}%` : 'N/A')
                      }
                    </span>
                  </div>
                )}
                {(question.distinction_list?.length > 0 || question.distinction !== undefined) && (
                  <div className="flex items-center gap-1">
                    <span className="hebrew-text font-medium">הבחנה:</span>
                    <span>
                      {question.distinction_list?.length > 0 
                        ? question.distinction_list.join(', ')
                        : (question.distinction != null ? question.distinction : 'N/A')
                      }
                    </span>
                  </div>
                )}
                {/* Add Performance Data Button */}
                {canEdit && question.source === 'uploaded' && (
                  <PerformanceDataDialog questionId={question.id} onUpdate={onUpdateQuestion} />
                )}
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function PerformanceDataDialog({ questionId, onUpdate }) {
  const [open, setOpen] = useState(false)
  const [accuracy, setAccuracy] = useState('')
  const [distinction, setDistinction] = useState('')
  const [loading, setLoading] = useState(false)

  const handleSubmit = async () => {
    if (!accuracy && !distinction) {
      alert('יש להזין לפחות ערך אחד')
      return
    }

    setLoading(true)
    try {
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}/add-performance`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          accuracy: accuracy ? parseFloat(accuracy) : null,
          distinction: distinction ? parseFloat(distinction) : null
        })
      })

      if (response.ok) {
        const result = await response.json()
        if (onUpdate) {
          onUpdate(questionId, result.question)
        }
        setOpen(false)
        setAccuracy('')
        setDistinction('')
        alert('נתוני ביצועים נוספו בהצלחה')
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בהוספת נתוני ביצועים')
      }
    } catch (error) {
      alert('שגיאה בהוספת נתוני ביצועים')
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="hebrew-text">
          <Plus className="w-3 h-3 ml-1" />
          הוסף נתוני ביצועים
        </Button>
      </DialogTrigger>
      <DialogContent className="hebrew-text">
        <DialogHeader>
          <DialogTitle className="hebrew-text">הוספת נתוני ביצועים</DialogTitle>
          <DialogDescription className="hebrew-text">
            הוסף נתוני דיוק והבחנה מבחינה שבה השתמשת בשאלה זו
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div>
            <label className="hebrew-text block text-sm font-medium mb-1">דיוק (%)</label>
            <Input
              type="number"
              min="0"
              max="100"
              step="0.1"
              value={accuracy}
              onChange={(e) => setAccuracy(e.target.value)}
              placeholder="0-100"
              className="hebrew-text"
            />
          </div>
          <div>
            <label className="hebrew-text block text-sm font-medium mb-1">הבחנה</label>
            <Input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={distinction}
              onChange={(e) => setDistinction(e.target.value)}
              placeholder="0-1"
              className="hebrew-text"
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} className="hebrew-text">
            ביטול
          </Button>
          <Button onClick={handleSubmit} disabled={loading} className="hebrew-text">
            {loading ? 'מוסיף...' : 'הוסף'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function CategoryList({ categories, selectedCategory, onSelectCategory, onEditCategory, canEdit = false }) {
  const [editingCategory, setEditingCategory] = useState(null)
  const [newCategoryName, setNewCategoryName] = useState('')
  const totalQuestions = categories.reduce((sum, cat) => sum + cat.question_count, 0)
  
  const handleEditCategory = (category) => {
    setEditingCategory(category.name)
    setNewCategoryName(category.name)
  }

  const handleSaveCategory = async () => {
    if (onEditCategory && newCategoryName.trim() && newCategoryName !== editingCategory) {
      await onEditCategory(editingCategory, newCategoryName.trim())
    }
    setEditingCategory(null)
    setNewCategoryName('')
  }

  const handleCancelEdit = () => {
    setEditingCategory(null)
    setNewCategoryName('')
  }
  
  return (
    <div className="space-y-2">
      <Button
        variant={selectedCategory === null ? "default" : "outline"}
        className="w-full justify-between hebrew-text"
        onClick={() => onSelectCategory(null)}
      >
        <span>כל השאלות</span>
        <Badge variant="secondary">
          {totalQuestions}
        </Badge>
      </Button>
      {categories.map((category, index) => (
        <div key={index} className="relative">
          {editingCategory === category.name ? (
            <div className="space-y-2 p-2 border rounded-md bg-gray-50">
              <Input
                value={newCategoryName}
                onChange={(e) => setNewCategoryName(e.target.value)}
                className="hebrew-text text-right"
                placeholder="שם נושא חדש"
              />
              <div className="flex gap-2">
                <Button size="sm" onClick={handleSaveCategory} className="hebrew-text">
                  שמור
                </Button>
                <Button size="sm" variant="outline" onClick={handleCancelEdit} className="hebrew-text">
                  ביטול
                </Button>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-1">
              <Button
                variant={selectedCategory === category.name ? "default" : "outline"}
                className="flex-1 justify-between hebrew-text text-right"
                onClick={() => onSelectCategory(category.name)}
              >
                <span>{category.name}</span>
                <Badge variant="secondary">{category.question_count}</Badge>
              </Button>
              {canEdit && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => handleEditCategory(category)}
                  className="text-gray-600 hover:text-gray-800"
                >
                  <Edit3 className="w-3 h-3" />
                </Button>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function UploadSection({ onUploadSuccess }) {
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [uploadResult, setUploadResult] = useState(null)
  const [exporting, setExporting] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [showClearDialog, setShowClearDialog] = useState(false)
  const [clearConfirmText, setClearConfirmText] = useState('')

  const handleFileChange = (e) => {
    setFile(e.target.files[0])
    setUploadResult(null)
  }

  const handleUpload = async () => {
    if (!file) return
    
    setUploading(true)
    setUploadResult(null)
    
    try {
      const formData = new FormData()
      formData.append('file', file)
      
      const response = await fetch(`${API_BASE_URL}/upload-excel`, {
        method: 'POST',
        body: formData
      })
      
      const result = await response.json()
      
      if (response.ok) {
        setUploadResult({
          success: true,
          message: `הועלו בהצלחה ${result.created_questions} שאלות חדשות`,
          details: result
        })
        setFile(null)
        if (onUploadSuccess) onUploadSuccess()
      } else {
        setUploadResult({
          success: false,
          message: result.error || 'שגיאה בהעלאת הקובץ'
        })
      }
    } catch (error) {
      setUploadResult({
        success: false,
        message: 'שגיאה בחיבור לשרת העלאה'
      })
    } finally {
      setUploading(false)
    }
  }

  const handleExport = async () => {
    setExporting(true)
    try {
      const response = await fetch(`${API_BASE_URL}/export-excel`)
      
      if (response.ok) {
        // Get the Excel content as blob
        const blob = await response.blob()
        
        // Create and download Excel file
        const link = document.createElement('a')
        const url = URL.createObjectURL(blob)
        link.setAttribute('href', url)
        link.setAttribute('download', `questions_export_${new Date().toISOString().slice(0,10)}.xlsx`)
        link.style.visibility = 'hidden'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        
        setUploadResult({
          success: true,
          message: 'השאלות יוצאו בהצלחה לקובץ Excel'
        })
      } else {
        const result = await response.json()
        setUploadResult({
          success: false,
          message: result.error || 'שגיאה בייצוא השאלות'
        })
      }
    } catch (error) {
      setUploadResult({
        success: false,
        message: 'שגיאה בחיבור לשרת'
      })
    } finally {
      setExporting(false)
    }
  }


  const handleDownloadTemplate = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/download-template`)
      
      if (response.ok) {
        // Get the Excel content as blob
        const blob = await response.blob()
        
        // Create and download Excel file
        const link = document.createElement('a')
        const url = URL.createObjectURL(blob)
        link.setAttribute('href', url)
        link.setAttribute('download', 'Template_For_Upload.xlsx')
        link.style.visibility = 'hidden'
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        
        setUploadResult({
          success: true,
          message: 'תבנית העלאה הורדה בהצלחה'
        })
      } else {
        const result = await response.json()
        setUploadResult({
          success: false,
          message: result.error || 'שגיאה בהורדת התבנית'
        })
      }
    } catch (error) {
      setUploadResult({
        success: false,
        message: 'שגיאה בחיבור לשרת'
      })
    }
  }

  const handleClearAll = async () => {
    if (clearConfirmText !== 'מחק הכל') {
      alert('יש להקליד "מחק הכל" בדיוק כדי לאשר')
      return
    }

    setClearing(true)
    try {
      const response = await fetch(`${API_BASE_URL}/clear-all`, {
        method: 'DELETE'
      })
      
      const result = await response.json()
      
      if (response.ok) {
        setUploadResult({
          success: true,
          message: 'כל השאלות נמחקו בהצלחה'
        })
        setShowClearDialog(false)
        setClearConfirmText('')
        if (onUploadSuccess) onUploadSuccess()
      } else {
        setUploadResult({
          success: false,
          message: result.error || 'שגיאה במחיקת השאלות'
        })
      }
    } catch (error) {
      setUploadResult({
        success: false,
        message: 'שגיאה בחיבור לשרת'
      })
    } finally {
      setClearing(false)
      setShowClearDialog(false)
      setClearConfirmText('')
    }
  }
  
  return (
    <div className="space-y-6">
      {/* Upload Section */}
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text flex items-center gap-2">
            <Upload className="w-5 h-5" />
            העלאת שאלות חדשות
          </CardTitle>
          <CardDescription className="hebrew-text">
            העלה קובץ Excel עם שאלות חדשות במבנה הנדרש. השאלות החדשות יתווספו לשאלות הקיימות.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div>
              <Input
                type="file"
                accept=".xlsx,.xls"
                onChange={handleFileChange}
                className="hebrew-text"
              />
            </div>
            {file && (
              <div className="hebrew-text text-sm text-gray-600">
                קובץ נבחר: {file.name}
              </div>
            )}
            <div className="flex gap-4">
              <Button 
                onClick={handleUpload} 
                disabled={!file || uploading}
                className="hebrew-text"
              >
                {uploading ? 'מעלה...' : 'העלה קובץ'}
              </Button>
              <Button 
                onClick={handleDownloadTemplate}
                variant="outline"
                className="hebrew-text"
              >
                <Download className="w-4 h-4 ml-2" />
                הורד תבנית העלאה
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Management Section */}
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">ניהול שאלות</CardTitle>
          <CardDescription className="hebrew-text">
            ייצוא ומחיקה של כל השאלות במערכת
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex gap-4">
              <Button 
                onClick={handleExport}
                disabled={exporting}
                variant="outline"
                className="hebrew-text"
              >
                {exporting ? 'מייצא...' : 'ייצא כל השאלות לקובץ Excel'}
              </Button>
              
              <Dialog open={showClearDialog} onOpenChange={setShowClearDialog}>
                <DialogTrigger asChild>
                  <Button 
                    variant="destructive"
                    className="hebrew-text"
                  >
                    מחק את כל השאלות
                  </Button>
                </DialogTrigger>
                <DialogContent className="hebrew-text">
                  <DialogHeader>
                    <DialogTitle className="hebrew-text">מחיקת כל השאלות</DialogTitle>
                    <DialogDescription className="hebrew-text">
                      פעולה זו תמחק את כל השאלות במערכת ולא ניתן לבטלה!
                      <br />
                      <strong>הקלד "מחק הכל" כדי לאשר:</strong>
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <Input
                      value={clearConfirmText}
                      onChange={(e) => setClearConfirmText(e.target.value)}
                      placeholder="הקלד: מחק הכל"
                      className="hebrew-text"
                    />
                  </div>
                  <DialogFooter className="gap-2">
                    <Button 
                      variant="outline" 
                      onClick={() => {
                        setShowClearDialog(false)
                        setClearConfirmText('')
                      }}
                      className="hebrew-text"
                    >
                      ביטול
                    </Button>
                    <Button 
                      variant="destructive" 
                      onClick={handleClearAll}
                      disabled={clearing || clearConfirmText !== 'מחק הכל'}
                      className="hebrew-text"
                    >
                      {clearing ? 'מוחק...' : 'מחק את כל השאלות'}
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Results */}
      {uploadResult && (
        <div className={`p-4 rounded-lg ${
          uploadResult.success 
            ? 'bg-green-50 border border-green-200 text-green-800' 
            : 'bg-yellow-50 border border-yellow-200 text-yellow-800'
        }`}>
          <div className="hebrew-text">
            {uploadResult.message}
          </div>
          {uploadResult.details && uploadResult.details.errors && uploadResult.details.errors.length > 0 && (
            <div className="mt-2 text-sm">
              <div className="hebrew-text font-medium">שגיאות:</div>
              <ul className="list-disc list-inside">
                {uploadResult.details.errors.map((error, index) => (
                  <li key={index} className="hebrew-text">{error}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function TestGenerationSection() {
  const [categories, setCategories] = useState([])
  const [categorySelections, setCategorySelections] = useState({})
  const [totalQuestions, setTotalQuestions] = useState(0)
  const [generatedTest, setGeneratedTest] = useState(null)
  const [isGenerating, setIsGenerating] = useState(false)
  const [excludeQuestions, setExcludeQuestions] = useState([])
  const [excludeFile, setExcludeFile] = useState(null)
  const [distinctionThreshold, setDistinctionThreshold] = useState(0.3)

  useEffect(() => {
    fetchTestCategories()
  }, [])

  const fetchTestCategories = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/test/categories`)
      if (response.ok) {
        const data = await response.json()
        setCategories(data)
      }
    } catch (error) {
      console.error('Error fetching categories:', error)
    }
  }

  const handleCategoryChange = (categoryName, count) => {
    const newSelections = { ...categorySelections }
    if (count > 0) {
      newSelections[categoryName] = count
    } else {
      delete newSelections[categoryName]
    }
    setCategorySelections(newSelections)
    
    // Update total questions
    const total = Object.values(newSelections).reduce((sum, count) => sum + count, 0)
    setTotalQuestions(total)
  }

  const handleExcludeFileUpload = async (event) => {
    const file = event.target.files[0]
    if (file && (file.name.endsWith('.xlsx') || file.name.endsWith('.xls'))) {
      setExcludeFile(file)
      
      try {
        const formData = new FormData()
        formData.append('file', file)
        
        const response = await fetch(`${API_BASE_URL}/test/upload-exclusion`, {
          method: 'POST',
          body: formData
        })
        
        if (response.ok) {
          const data = await response.json()
          setExcludeQuestions(data.excluded_question_ids)
          console.log(`Loaded exclusion file: ${data.total_excluded} questions to exclude`)
        } else {
          const error = await response.json()
          alert(`שגיאה בטעינת קובץ ההחרגה: ${error.error}`)
          setExcludeFile(null)
          setExcludeQuestions([])
        }
      } catch (error) {
        console.error('Error uploading exclusion file:', error)
        alert('שגיאה בטעינת קובץ ההחרגה')
        setExcludeFile(null)
        setExcludeQuestions([])
      }
    } else {
      alert('יש להעלות קובץ Excel בלבד (.xlsx או .xls)')
    }
  }

  const generateTest = async () => {
    if (totalQuestions === 0) {
      alert('יש לבחור לפחות שאלה אחת')
      return
    }

    setIsGenerating(true)
    try {
      const response = await fetch(`${API_BASE_URL}/test/generate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          categories: categorySelections,
          exclude_questions: excludeQuestions
        })
      })

      if (response.ok) {
        const data = await response.json()
        setGeneratedTest(data)
      } else {
        const error = await response.json()
        alert(`שגיאה: ${error.error}`)
      }
    } catch (error) {
      console.error('Error generating test:', error)
      alert('שגיאה ביצירת המבחן')
    } finally {
      setIsGenerating(false)
    }
  }

  const exportTestDocx = async (includeAnswers = false) => {
    if (!generatedTest) return

    try {
      const response = await fetch(`${API_BASE_URL}/test/export-docx`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          questions: generatedTest.questions,
          include_answers: includeAnswers
        })
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.style.display = 'none'
        a.href = url
        
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_')
        const suffix = includeAnswers ? '_with_answers' : ''
        a.download = `test_exam${suffix}_${timestamp}.docx`
        
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } else {
        alert('שגיאה בייצוא המבחן')
      }
    } catch (error) {
      console.error('Error exporting test:', error)
      alert('שגיאה בייצוא המבחן')
    }
  }

  const exportTestExcel = async () => {
    if (!generatedTest) return

    try {
      const response = await fetch(`${API_BASE_URL}/test/export-excel`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          questions: generatedTest.questions
        })
      })

      if (response.ok) {
        const blob = await response.blob()
        const url = window.URL.createObjectURL(blob)
        const a = document.createElement('a')
        a.style.display = 'none'
        a.href = url
        
        const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_')
        a.download = `test_questions_tracking_${timestamp}.xlsx`
        
        document.body.appendChild(a)
        a.click()
        window.URL.revokeObjectURL(url)
        document.body.removeChild(a)
      } else {
        alert('שגיאה בייצוא קובץ המעקב')
      }
    } catch (error) {
      console.error('Error exporting Excel:', error)
      alert('שגיאה בייצוא קובץ המעקב')
    }
  }

  const replaceQuestion = async (questionId, categoryName) => {
    try {
      const response = await fetch(`${API_BASE_URL}/test/replace-question`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          question_id: questionId,
          category: categoryName,
          exclude_questions: excludeQuestions,
          current_test_questions: generatedTest.questions
        })
      })

      if (response.ok) {
        const data = await response.json()
        
        // Update the generated test with the replacement question
        const updatedQuestions = generatedTest.questions.map(q => {
          if (q.id === questionId) {
            return {
              ...data.replacement_question,
              number: q.number // Keep the original question number
            }
          }
          return q
        })
        
        setGeneratedTest({
          ...generatedTest,
          questions: updatedQuestions
        })
      } else {
        const error = await response.json()
        alert(`שגיאה: ${error.error}`)
      }
    } catch (error) {
      console.error('Error replacing question:', error)
      alert('שגיאה בהחלפת השאלה')
    }
  }

  const resetTest = () => {
    setGeneratedTest(null)
    setCategorySelections({})
    setTotalQuestions(0)
    setExcludeQuestions([])
    setExcludeFile(null)
    
    // Clear the file input
    const fileInput = document.querySelector('input[type="file"][accept=".xlsx,.xls"]')
    if (fileInput) {
      fileInput.value = ''
    }
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="hebrew-text">יצירת מבחן</CardTitle>
          <CardDescription className="hebrew-text">
            בחר מספר שאלות מכל קטגוריה ליצירת מבחן מותאם אישית
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!generatedTest ? (
            <div className="space-y-6">
              {/* Category Selection */}
              <div className="space-y-4">
                <h3 className="hebrew-text font-semibold">בחירת שאלות לפי קטגוריה</h3>
                {categories.map((category) => (
                  <div key={category.name} className="flex items-center justify-between p-4 border rounded-lg">
                    <div className="hebrew-text">
                      <span className="font-medium">{category.name}</span>
                      <span className="text-gray-500 mr-2">({category.question_count} שאלות זמינות)</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Input
                        type="number"
                        min="0"
                        max={category.question_count}
                        value={categorySelections[category.name] || 0}
                        onChange={(e) => handleCategoryChange(category.name, parseInt(e.target.value) || 0)}
                        className="w-20 text-center"
                      />
                      <span className="hebrew-text text-sm text-gray-500">שאלות</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* Exclude Questions File Upload */}
              <div className="space-y-2">
                <h3 className="hebrew-text font-semibold">החרגת שאלות (אופציונלי)</h3>
                <p className="hebrew-text text-sm text-gray-600">
                  העלה קובץ Excel של מבחן קודם כדי להחריג שאלות שכבר נבחנו
                </p>
                <Input
                  type="file"
                  accept=".xlsx,.xls"
                  onChange={handleExcludeFileUpload}
                  className="hebrew-text"
                />
                {excludeFile && (
                  <p className="hebrew-text text-sm text-green-600">
                    קובץ נטען: {excludeFile.name} ({excludeQuestions.length} שאלות יוחרגו)
                  </p>
                )}
              </div>

              {/* Total Questions Display */}
              <div className="p-4 bg-blue-50 rounded-lg">
                <p className="hebrew-text font-semibold text-blue-800">
                  סה"כ שאלות במבחן: {totalQuestions}
                </p>
              </div>

              {/* Generate Button */}
              <Button
                onClick={generateTest}
                disabled={totalQuestions === 0 || isGenerating}
                className="w-full hebrew-text"
              >
                {isGenerating ? 'יוצר מבחן...' : 'צור מבחן'}
              </Button>
            </div>
          ) : (
            /* Generated Test Display */
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <h3 className="hebrew-text font-semibold">מבחן נוצר בהצלחה!</h3>
                <Button variant="outline" onClick={resetTest} className="hebrew-text">
                  צור מבחן חדש
                </Button>
              </div>

              <div className="p-4 bg-green-50 rounded-lg space-y-3">
                <p className="hebrew-text text-green-800">
                  המבחן כולל {generatedTest.total_questions} שאלות
                </p>
                <p className="hebrew-text text-sm text-green-600">
                  נוצר בתאריך: {new Date(generatedTest.generation_time).toLocaleString('he-IL')}
                </p>
                
                {/* Test Statistics */}
                <div className="border-t pt-3 space-y-2">
                  <h5 className="hebrew-text font-medium text-green-800">סטטיסטיקות המבחן</h5>
                  
                  {(() => {
                    // Calculate average accuracy - exclude only null values, keep 0 as valid
                    const accuracyValues = generatedTest.questions
                      .map(q => parseFloat(q.accuracy))
                      .filter(acc => !isNaN(acc) && acc != null)
                    const avgAccuracy = accuracyValues.length > 0 
                      ? (accuracyValues.reduce((sum, acc) => sum + acc, 0) / accuracyValues.length).toFixed(1)
                      : 'N/A'
                    
                    // Count questions above distinction threshold - exclude only null values, keep 0 as valid
                    const highDistinctionCount = generatedTest.questions
                      .filter(q => {
                        const distinction = parseFloat(q.distinction)
                        return !isNaN(distinction) && distinction != null && distinction > distinctionThreshold
                      }).length
                    
                    // Count total questions with valid distinction values (including 0)
                    const totalValidDistinction = generatedTest.questions
                      .filter(q => {
                        const distinction = parseFloat(q.distinction)
                        return !isNaN(distinction) && distinction != null
                      }).length
                    
                    return (
                      <div className="space-y-2">
                        <p className="hebrew-text text-sm text-green-700">
                          דיוק ממוצע: {avgAccuracy}%
                        </p>
                        
                        {/* Distinction Threshold Slider */}
                        <div className="space-y-2">
                          <div className="flex items-center gap-2">
                            <label className="hebrew-text text-sm text-green-700">
                              סף הבחנה:
                            </label>
                            <input
                              type="range"
                              min="0"
                              max="1"
                              step="0.1"
                              value={distinctionThreshold}
                              onChange={(e) => setDistinctionThreshold(parseFloat(e.target.value))}
                              className="flex-1"
                            />
                            <span className="text-sm text-green-700 min-w-[3rem]">
                              {distinctionThreshold.toFixed(1)}
                            </span>
                          </div>
                          <p className="hebrew-text text-sm text-green-700">
                            שאלות עם הבחנה גבוהה מ-{distinctionThreshold.toFixed(1)}: {highDistinctionCount} מתוך {totalValidDistinction}
                          </p>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </div>

              {/* Export Options */}
              <div className="space-y-4">
                <h4 className="hebrew-text font-semibold">ייצוא המבחן</h4>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <Button
                    onClick={() => exportTestDocx(false)}
                    className="hebrew-text"
                  >
                    ייצא מבחן (ללא תשובות)
                  </Button>
                  <Button
                    onClick={() => exportTestDocx(true)}
                    variant="outline"
                    className="hebrew-text"
                  >
                    ייצא דף תשובות
                  </Button>
                  <Button
                    onClick={exportTestExcel}
                    variant="outline"
                    className="hebrew-text"
                  >
                    ייצא קובץ מעקב (Excel)
                  </Button>
                </div>
              </div>

              {/* Preview Section */}
              <div className="space-y-4">
                <h4 className="hebrew-text font-semibold">תצוגה מקדימה</h4>
                <div className="max-h-96 overflow-y-auto space-y-6">
                  {(() => {
                    // Group questions by category
                    const questionsByCategory = {}
                    generatedTest.questions.forEach(question => {
                      const categories = question.categories || [question.category || 'ללא קטגוריה']
                      const primaryCategory = categories[0] || 'ללא קטגוריה'
                      
                      if (!questionsByCategory[primaryCategory]) {
                        questionsByCategory[primaryCategory] = []
                      }
                      questionsByCategory[primaryCategory].push(question)
                    })
                    
                    return Object.entries(questionsByCategory).map(([categoryName, questions]) => (
                      <div key={categoryName} className="space-y-3">
                        {/* Category Title */}
                        <h5 className="hebrew-text font-medium text-lg border-b pb-2 text-blue-700">
                          {categoryName}
                        </h5>
                        
                        {/* Questions in this category */}
                        {questions.map((question) => (
                          <Card key={question.id} className="p-4">
                            <div className="hebrew-text">
                              <div className="flex justify-between items-start mb-2">
                                <p className="font-semibold flex-1">
                                  {question.number}. {question.question}
                                </p>
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => replaceQuestion(question.id, categoryName)}
                                  className="hebrew-text mr-2 text-xs"
                                >
                                  החלף שאלה
                                </Button>
                              </div>
                              <div className="space-y-1 text-sm">
                                <p>א. {question.answer1}</p>
                                <p>ב. {question.answer2}</p>
                                <p>ג. {question.answer3}</p>
                                <p>ד. {question.answer4}</p>
                              </div>
                              <div className="mt-2 flex items-center gap-4 text-xs text-gray-500">
                                <span>תשובה נכונה: {question.correct_answer}</span>
                                <span>דיוק: {question.accuracy != null ? `${question.accuracy}%` : 'N/A'}</span>
                                <span>הבחנה: {question.distinction != null ? question.distinction : 'N/A'}</span>
                              </div>
                            </div>
                          </Card>
                        ))}
                      </div>
                    ))
                  })()}
                </div>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

function AboutSection() {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="hebrew-text flex items-center gap-2">
          <Info className="w-5 h-5" />
          אודות המערכת
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-4 hebrew-text">
          <div>
            <h3 className="font-semibold mb-2">מערכת היברידית אמינה</h3>
            <p className="text-gray-600">
              המערכת משלבת שאלות מוטמעות (תמיד זמינות) עם יכולת העלאה של שאלות חדשות.
              השאלות המוטמעות נטענות מיידית ולא תלויות בחיבור לשרת.
            </p>
          </div>
          
          <div>
            <h3 className="font-semibold mb-2">יתרונות המערכת</h3>
            <ul className="list-disc list-inside text-gray-600 space-y-1">
              <li>אמינות מלאה - השאלות המוטמעות תמיד זמינות</li>
              <li>מהירות טעינה - גישה מיידית לכל השאלות</li>
              <li>גמישות - אפשרות להוסיף שאלות חדשות</li>
              <li>תמיכה מלאה בעברית וכיוון RTL</li>
            </ul>
          </div>
          
          <div>
            <h3 className="font-semibold mb-2">מבנה קובץ CSV להעלאה</h3>
            <p className="text-gray-600 text-sm">
              הקובץ צריך לכלול עמודות: קטגוריה, שאלה, תשובה1, תשובה2, תשובה3, תשובה4, תשובה_נכונה
            </p>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function App() {
  const [uploadedQuestions, setUploadedQuestions] = useState([])
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [showAnswers, setShowAnswers] = useState({})
  const [sortBy, setSortBy] = useState('category') // Default sort by category
  const [sortOrder, setSortOrder] = useState('asc') // 'asc' or 'desc'

  // All questions are now uploaded questions
  const allQuestions = uploadedQuestions

  // Calculate categories from all questions
  const categories = React.useMemo(() => {
    const categoryMap = {}
    allQuestions.forEach(q => {
      if (!categoryMap[q.category]) {
        categoryMap[q.category] = 0
      }
      categoryMap[q.category]++
    })
    
    return Object.entries(categoryMap).map(([name, count]) => ({
      name,
      question_count: count
    }))
  }, [allQuestions])

  // Filter and sort questions
  const filteredQuestions = React.useMemo(() => {
    // First filter questions
    const filtered = allQuestions.filter(q => {
      // Check if question belongs to selected category (check all categories for the question)
      const matchesCategory = selectedCategory === null || 
        (q.categories && q.categories.includes(selectedCategory)) ||
        (!q.categories && q.category === selectedCategory)
      
      if (searchTerm === '') {
        return matchesCategory
      }

      const searchTermLower = searchTerm.toLowerCase()  // Standard English toLowerCase

      const matchesSearch = 
        // Search in question text
        q.question.toLowerCase().includes(searchTermLower) || 
        // Search in category
        q.category.toLowerCase().includes(searchTermLower) ||
        // Search in multiple categories
        (q.categories && q.categories.some(cat => cat.toLowerCase().includes(searchTermLower))) ||
        // Search in all answer options
        q.answer1.toLowerCase().includes(searchTermLower) ||
        q.answer2.toLowerCase().includes(searchTermLower) ||
        q.answer3.toLowerCase().includes(searchTermLower) ||
        q.answer4.toLowerCase().includes(searchTermLower)
      
      return matchesCategory && matchesSearch
    })

    // Then sort questions
    const sorted = [...filtered].sort((a, b) => {
      let aValue, bValue
      
      switch (sortBy) {
        case 'accuracy':
          aValue = a.accuracy || 0
          bValue = b.accuracy || 0
          break
        case 'distinction':
          aValue = a.distinction || 0
          bValue = b.distinction || 0
          break
        case 'upload_date':
          aValue = new Date(a.uploaded_at || a.created_at || 0)
          bValue = new Date(b.uploaded_at || b.created_at || 0)
          break
        case 'category':
        default:
          aValue = a.category || ''
          bValue = b.category || ''
          break
      }
      
      if (sortBy === 'category') {
        // For category sorting, use string comparison
        if (sortOrder === 'asc') {
          return aValue.localeCompare(bValue, 'he')
        } else {
          return bValue.localeCompare(aValue, 'he')
        }
      } else {
        // For numeric/date sorting
        if (sortOrder === 'asc') {
          return aValue < bValue ? -1 : aValue > bValue ? 1 : 0
        } else {
          return aValue > bValue ? -1 : aValue < bValue ? 1 : 0
        }
      }
    })

    return sorted
  }, [allQuestions, selectedCategory, searchTerm, sortBy, sortOrder])

  const toggleAnswer = (questionId) => {
    setShowAnswers(prev => ({
      ...prev,
      [questionId]: !prev[questionId]
    }))
  }

  const handleUploadSuccess = async () => {
    // Fetch uploaded questions from backend
    try {
      const response = await fetch(`${API_BASE_URL}/questions`)
      if (response.ok) {
        const uploadedData = await response.json()
        // Mark uploaded questions and add them
        const markedUploadedQuestions = uploadedData.map(q => ({
          ...q,
          source: 'uploaded'
        }))
        setUploadedQuestions(markedUploadedQuestions)
      }
    } catch (error) {
      console.log('Could not fetch uploaded questions from backend')
    }
  }

  // Try to load uploaded questions on mount
  useEffect(() => {
    handleUploadSuccess()
  }, [])

  // Editing functions
  const handleDeleteQuestion = async (questionId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}`, {
        method: 'DELETE'
      })
      
      if (response.ok) {
        // Remove from uploaded questions
        setUploadedQuestions(prev => prev.filter(q => q.id !== questionId))
        // Also remove from show answers
        setShowAnswers(prev => {
          const newAnswers = { ...prev }
          delete newAnswers[questionId]
          return newAnswers
        })
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה במחיקת השאלה')
      }
    } catch (error) {
      console.error('Error deleting question:', error)
      alert('שגיאה במחיקת השאלה')
    }
  }

  const handleChangeQuestionCategory = async (questionId, newCategory) => {
    try {
      const question = uploadedQuestions.find(q => q.id === questionId)
      if (!question) return

      const response = await fetch(`${API_BASE_URL}/questions/${questionId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          ...question,
          category: newCategory
        })
      })
      
      if (response.ok) {
        const updatedQuestion = await response.json()
        setUploadedQuestions(prev => 
          prev.map(q => q.id === questionId ? updatedQuestion : q)
        )
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בעדכון הקטגוריה')
      }
    } catch (error) {
      console.error('Error changing question category:', error)
      alert('שגיאה בעדכון הקטגוריה')
    }
  }

  const handleUpdateQuestion = async (questionId, updatedData) => {
    try {
      // If updatedData is a complete question object (from performance update), use it directly
      if (updatedData && typeof updatedData === 'object' && updatedData.id) {
        setUploadedQuestions(prev => 
          prev.map(q => q.id === questionId ? updatedData : q)
        )
        return
      }

      // Otherwise, it's a regular update - send to API
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(updatedData)
      })
      
      if (response.ok) {
        const updatedQuestion = await response.json()
        setUploadedQuestions(prev => 
          prev.map(q => q.id === questionId ? updatedQuestion : q)
        )
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בעדכון השאלה')
      }
    } catch (error) {
      console.error('Error updating question:', error)
      alert('שגיאה בעדכון השאלה')
    }
  }

  const handleEditCategory = async (oldCategoryName, newCategoryName) => {
    try {
      const response = await fetch(`${API_BASE_URL}/categories/${encodeURIComponent(oldCategoryName)}`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          name: newCategoryName
        })
      })
      
      if (response.ok) {
        // Update all questions with the old category name
        setUploadedQuestions(prev => 
          prev.map(q => 
            q.category === oldCategoryName 
              ? { ...q, category: newCategoryName }
              : q
          )
        )
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בעדכון שם הנושא')
      }
    } catch (error) {
      console.error('Error editing category:', error)
      alert('שגיאה בעדכון שם הנושא')
    }
  }

  const handleAddSecondaryCategory = async (questionId) => {
    // Show a dialog to select a category to add
    const availableCategories = categories.filter(cat => {
      const question = uploadedQuestions.find(q => q.id === questionId)
      if (!question) return false
      
      const questionCategories = question.categories || [question.category]
      return !questionCategories.includes(cat.name)
    })
    
    if (availableCategories.length === 0) {
      alert('אין קטגוריות זמינות להוספה')
      return
    }
    
    // Simple prompt for now - could be enhanced with a proper dialog
    const categoryNames = availableCategories.map(cat => cat.name).join('\n')
    const selectedCategory = prompt(`בחר קטגוריה להוספה:\n${categoryNames}`)
    
    if (!selectedCategory || !availableCategories.some(cat => cat.name === selectedCategory)) {
      return
    }
    
    try {
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}/add-category`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          category: selectedCategory
        })
      })
      
      if (response.ok) {
        const result = await response.json()
        setUploadedQuestions(prev => 
          prev.map(q => q.id === questionId ? result.question : q)
        )
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בהוספת קטגוריה')
      }
    } catch (error) {
      console.error('Error adding secondary category:', error)
      alert('שגיאה בהוספת קטגוריה')
    }
  }

  const handleRemoveSecondaryCategory = async (questionId, categoryToRemove) => {
    if (!confirm(`האם אתה בטוח שברצונך להסיר את הקטגוריה "${categoryToRemove}" מהשאלה?`)) {
      return
    }
    
    try {
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}/remove-category`, {
        method: 'DELETE',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          category: categoryToRemove
        })
      })
      
      if (response.ok) {
        const result = await response.json()
        setUploadedQuestions(prev => 
          prev.map(q => q.id === questionId ? result.question : q)
        )
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בהסרת קטגוריה')
      }
    } catch (error) {
      console.error('Error removing secondary category:', error)
      alert('שגיאה בהסרת קטגוריה')
    }
  }

  const handleDuplicateQuestion = async (questionId) => {
    try {
      const response = await fetch(`${API_BASE_URL}/questions/${questionId}/duplicate`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        }
      })
      
      if (response.ok) {
        const result = await response.json()
        // Add the new question to the list
        setUploadedQuestions(prev => [...prev, result.question])
        alert('השאלה שוכפלה בהצלחה!')
      } else {
        const error = await response.json()
        alert(error.error || 'שגיאה בשכפול השאלה')
      }
    } catch (error) {
      console.error('Error duplicating question:', error)
      alert('שגיאה בשכפול השאלה')
    }
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm border-b">
        <div className="max-w-7xl mx-auto px-4 py-6">
          <div className="flex items-center gap-3">
            <BookOpen className="w-8 h-8 text-blue-600" />
            <h1 className="text-3xl font-bold hebrew-text">
              מאגר שאלות בחינה בעברית
            </h1>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 py-8">
        <Tabs defaultValue="questions" className="w-full">
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="questions" className="hebrew-text">
              עיון בשאלות
            </TabsTrigger>
            <TabsTrigger value="upload" className="hebrew-text">
              העלאת שאלות
            </TabsTrigger>
            <TabsTrigger value="test-generation" className="hebrew-text">
              יצירת מבחן
            </TabsTrigger>
            <TabsTrigger value="about" className="hebrew-text">
              אודות המערכת
            </TabsTrigger>
          </TabsList>

          <TabsContent value="questions" className="mt-6">
            <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
              {/* Sidebar */}
              <div className="lg:col-span-1">
                <Card>
                  <CardHeader>
                    <CardTitle className="hebrew-text">נושאים</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <CategoryList
                      categories={categories}
                      selectedCategory={selectedCategory}
                      onSelectCategory={setSelectedCategory}
                      onEditCategory={handleEditCategory}
                      canEdit={true}
                    />
                  </CardContent>
                </Card>
              </div>

              {/* Main content */}
              <div className="lg:col-span-3">
                {/* Search and Sort */}
                <div className="mb-6 space-y-4">
                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400 w-4 h-4" />
                    <Input
                      placeholder="חיפוש שאלות..."
                      value={searchTerm}
                      onChange={(e) => setSearchTerm(e.target.value)}
                      className="pl-10 hebrew-text"
                    />
                  </div>
                  
                  {/* Sorting Controls */}
                  <div className="flex items-center gap-4 p-4 bg-gray-50 rounded-lg">
                    <span className="hebrew-text font-medium text-sm">מיון לפי:</span>
                    <select
                      value={sortBy}
                      onChange={(e) => setSortBy(e.target.value)}
                      className="px-3 py-2 border rounded-md hebrew-text text-sm"
                    >
                      <option value="category">קטגוריה</option>
                      <option value="accuracy">דיוק</option>
                      <option value="distinction">הבחנה</option>
                      <option value="upload_date">תאריך העלאה</option>
                    </select>
                    
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')}
                      className="hebrew-text"
                    >
                      {sortOrder === 'asc' ? '↑ עולה' : '↓ יורד'}
                    </Button>
                    
                    <span className="text-sm text-gray-500 hebrew-text">
                      {filteredQuestions.length} שאלות
                    </span>
                  </div>
                </div>

                {/* Questions */}
                <div className="space-y-4">
                  {filteredQuestions.length === 0 ? (
                    <Card>
                      <CardContent className="text-center py-8">
                        <p className="hebrew-text text-gray-500">
                          לא נמצאו שאלות התואמות את החיפוש
                        </p>
                      </CardContent>
                    </Card>
                  ) : (
                    filteredQuestions.map((question) => (
                      <QuestionCard
                        key={`${question.source}-${question.id}`}
                        question={question}
                        showAnswer={showAnswers[`${question.source}-${question.id}`] || false}
                        onToggleAnswer={() => toggleAnswer(`${question.source}-${question.id}`)}
                        categories={categories}
                        onDeleteQuestion={handleDeleteQuestion}
                        onChangeCategory={handleChangeQuestionCategory}
                        onUpdateQuestion={handleUpdateQuestion}
                        onAddSecondaryCategory={handleAddSecondaryCategory}
                        onRemoveSecondaryCategory={handleRemoveSecondaryCategory}
                        onDuplicateQuestion={handleDuplicateQuestion}
                        canEdit={true}
                      />
                    ))
                  )}
                </div>
              </div>
            </div>
          </TabsContent>

          <TabsContent value="upload" className="mt-6">
            <div className="max-w-2xl mx-auto">
              <UploadSection onUploadSuccess={handleUploadSuccess} />
            </div>
          </TabsContent>

          <TabsContent value="test-generation" className="mt-6">
            <div className="max-w-4xl mx-auto">
              <TestGenerationSection />
            </div>
          </TabsContent>

          <TabsContent value="about" className="mt-6">
            <div className="max-w-4xl mx-auto">
              <AboutSection />
            </div>
          </TabsContent>
        </Tabs>
      </main>
    </div>
  )
}

export default App

