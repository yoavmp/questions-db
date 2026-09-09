"""
Category ordering utility for Hebrew exam system
"""

# Predefined category order
CATEGORY_ORDER = [
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

def get_category_order_index(category_name):
    """
    Get the order index for a category.
    Categories not in the predefined list will get a high index for alphabetical sorting.
    """
    try:
        return CATEGORY_ORDER.index(category_name)
    except ValueError:
        # Category not in predefined list, return high index for alphabetical sorting
        return len(CATEGORY_ORDER) + 1000

def sort_categories(categories):
    """
    Sort a list of category names according to the predefined order.
    Categories not in the predefined list will be sorted alphabetically at the end.
    """
    def sort_key(category):
        order_index = get_category_order_index(category)
        if order_index >= len(CATEGORY_ORDER) + 1000:
            # For categories not in predefined list, sort alphabetically
            return (order_index, category)
        else:
            # For predefined categories, use order index
            return (order_index, '')
    
    return sorted(categories, key=sort_key)

def sort_questions_by_category(questions):
    """
    Sort a list of questions by category according to the predefined order.
    Within each category, questions maintain their original order.
    """
    def sort_key(question):
        category = question.get('category', '') if isinstance(question, dict) else getattr(question, 'category', '')
        order_index = get_category_order_index(category)
        return order_index
    
    return sorted(questions, key=sort_key)

def group_questions_by_category(questions):
    """
    Group questions by category and return them in the predefined category order.
    Returns a list of tuples: (category_name, questions_list)
    """
    # Group questions by category
    category_groups = {}
    for question in questions:
        category = question.get('category', '') if isinstance(question, dict) else getattr(question, 'category', '')
        if category not in category_groups:
            category_groups[category] = []
        category_groups[category].append(question)
    
    # Sort categories and return grouped questions
    sorted_categories = sort_categories(list(category_groups.keys()))
    
    result = []
    for category in sorted_categories:
        if category in category_groups:
            result.append((category, category_groups[category]))
    
    return result

