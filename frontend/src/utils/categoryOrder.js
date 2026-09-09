// Category ordering utility for frontend
const CATEGORY_ORDER = [
  'מבוא',
  'התעלה השדרתית ותכולתה',
  'אמבריולוגיה',
  'טופוגרפיה של ההמיספרות',
  'חומר לבן',
  'חדרי המוח',
  'גרעיני הבסיס',
  'היסטולוגיה',
  'לוקליזציה פונקציונלית',
  'תאי מערכת העצבים',
  'מיפוי ודימות מוחי',
  'אספקת דם',
  'קרומים וסינוסים דוראליים',
  'גזע המוח',
  'עצבים קרניאליים',
  'מסילות עצביות',
  'המוח הקטן',
  'דיאנצפלון',
  'המערכת הלימבית',
  'מערכת העצבים ההיקפית'
]

export function getCategoryOrderIndex(categoryName) {
  const index = CATEGORY_ORDER.indexOf(categoryName)
  return index !== -1 ? index : CATEGORY_ORDER.length + 1000
}

export function sortCategories(categories) {
  return categories.sort((a, b) => {
    const indexA = getCategoryOrderIndex(a)
    const indexB = getCategoryOrderIndex(b)
    
    if (indexA !== indexB) {
      return indexA - indexB
    }
    
    // If both are not in predefined list, sort alphabetically
    if (indexA >= CATEGORY_ORDER.length + 1000 && indexB >= CATEGORY_ORDER.length + 1000) {
      return a.localeCompare(b, 'he')
    }
    
    return 0
  })
}

export function groupQuestionsByCategory(questions) {
  // Group questions by category
  const categoryGroups = {}
  
  questions.forEach(question => {
    const categories = question.categories || [question.category || 'ללא קטגוריה']
    const primaryCategory = categories[0] || 'ללא קטגוריה'
    
    if (!categoryGroups[primaryCategory]) {
      categoryGroups[primaryCategory] = []
    }
    categoryGroups[primaryCategory].push(question)
  })
  
  // Sort categories and return grouped questions
  const sortedCategories = sortCategories(Object.keys(categoryGroups))
  
  return sortedCategories.map(category => ({
    category,
    questions: categoryGroups[category]
  }))
}