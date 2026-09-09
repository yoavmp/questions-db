import csv
import os
import json
from flask import Blueprint, request, jsonify, make_response
from datetime import datetime
from src.models.user import db
from src.models.question import Question, Category
import openpyxl
from openpyxl import Workbook
from io import BytesIO

upload_bp = Blueprint('upload', __name__)

def migrate_json_to_db():
    """Migrate existing JSON data to database"""
    try:
        # Check if we already have data in the database
        if Question.query.count() > 0:
            print("Database already has questions, skipping migration")
            return
            
        # Try to load from JSON file
        json_file = os.path.join(os.path.dirname(__file__), '..', 'data', 'questions.json')
        if os.path.exists(json_file):
            import json
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            print(f"Migrating {len(data.get('questions', []))} questions from JSON to database...")
            
            for q_data in data.get('questions', []):
                question = Question.from_dict(q_data)
                db.session.add(question)
            
            db.session.commit()
            update_categories()
            print("Migration completed successfully!")
        else:
            print("No JSON file found, starting with empty database")
            
    except Exception as e:
        print(f"Error during migration: {e}")
        db.session.rollback()

def update_categories():
    """Update categories based on current questions"""
    try:
        # Clear existing categories
        Category.query.delete()
        
        # Count questions per category
        category_counts = {}
        total_questions = Question.query.count()
        
        for question in Question.query.all():
            categories = question.categories
            for category in categories:
                if category not in category_counts:
                    category_counts[category] = 0
                category_counts[category] += 1
        
        # Add "All Questions" category
        if total_questions > 0:
            all_category = Category(name="כל השאלות", question_count=total_questions)
            db.session.add(all_category)
        
        # Add individual categories
        for category_name, count in category_counts.items():
            category = Category(name=category_name, question_count=count)
            db.session.add(category)
        
        db.session.commit()
        
    except Exception as e:
        print(f"Error updating categories: {e}")
        db.session.rollback()

@upload_bp.route('/questions', methods=['GET'])
def get_questions():
    """Get all questions"""
    try:
        questions = Question.query.all()
        return jsonify([q.to_dict() for q in questions])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all categories"""
    try:
        categories = Category.query.all()
        return jsonify([c.to_dict() for c in categories])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/upload-excel', methods=['POST'])
def upload_excel():
    """Upload questions from Excel file"""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "לא נבחר קובץ"}), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify({"error": "לא נבחר קובץ"}), 400
        
        if not file.filename.lower().endswith(('.xlsx', '.xls')):
            return jsonify({"error": "יש להעלות קובץ Excel בלבד (.xlsx או .xls)"}), 400
        
        # Read Excel content
        try:
            workbook = openpyxl.load_workbook(file, data_only=True)
            worksheet = workbook.active
            
            # Convert Excel to list of dictionaries
            headers = []
            for cell in worksheet[1]:
                headers.append(cell.value if cell.value else "")
            
            excel_data = []
            for row in worksheet.iter_rows(min_row=2, values_only=True):
                if any(cell is not None for cell in row):  # Skip empty rows
                    row_dict = {}
                    for i, value in enumerate(row):
                        if i < len(headers):
                            row_dict[headers[i]] = value if value is not None else ""
                    excel_data.append(row_dict)
                    
        except Exception as e:
            return jsonify({"error": f"שגיאה בקריאת קובץ Excel: {str(e)}"}), 400
        
        # Map Hebrew headers to English
        header_mapping = {
            'נושא': 'category',
            'קטגוריה': 'category', 
            'שאלה': 'question',
            'תשובה1': 'answer1',
            'תשובה2': 'answer2', 
            'תשובה3': 'answer3',
            'תשובה4': 'answer4',
            'תשובה_נכונה': 'correct_answer',
            'דיוק': 'accuracy',
            'הבחנה': 'distinction',
            'נושא2': 'category2',
            'נושא3': 'category3'
        }
        
        questions_added = 0
        errors = []
        
        # Get the next available ID
        max_id = db.session.query(db.func.max(Question.id)).scalar() or 0
        next_id = max_id + 1
        
        # Process each row from Excel data
        for row_num, row_data in enumerate(excel_data, start=2):  # Start from 2 since row 1 is headers
            try:
                # Map headers
                mapped_row = {}
                for hebrew_key, value in row_data.items():
                    english_key = header_mapping.get(hebrew_key.strip() if hebrew_key else '', hebrew_key.strip() if hebrew_key else '')
                    mapped_row[english_key] = str(value).strip() if value is not None else ''
                
                # Validate required fields
                required_fields = ['category', 'question', 'answer1', 'answer2', 'answer3', 'answer4', 'correct_answer']
                missing_fields = [field for field in required_fields if not mapped_row.get(field)]
                
                if missing_fields:
                    errors.append(f"שורה {row_num}: חסרים שדות: {', '.join(missing_fields)}")
                    continue
                
                # Parse correct answer
                try:
                    correct_answer_id = int(mapped_row['correct_answer'])
                    if correct_answer_id not in [1, 2, 3, 4]:
                        raise ValueError()
                except ValueError:
                    errors.append(f"שורה {row_num}: תשובה נכונה חייבת להיות מספר בין 1-4")
                    continue
                
                # Parse performance measures - support both single values and JSON arrays
                accuracy_values = []
                distinction_values = []
                
                # Handle accuracy
                if mapped_row.get('accuracy'):
                    accuracy_str = str(mapped_row['accuracy']).strip()
                    if accuracy_str:
                        try:
                            # Try to parse as JSON array first
                            if accuracy_str.startswith('[') and accuracy_str.endswith(']'):
                                accuracy_values = json.loads(accuracy_str)
                                accuracy_values = [float(v) for v in accuracy_values if v is not None]
                            else:
                                # Parse as single value
                                accuracy_val = float(accuracy_str)
                                if accuracy_val != 0:  # Only add non-zero values
                                    accuracy_values = [accuracy_val]
                        except (ValueError, json.JSONDecodeError):
                            pass
                
                # Handle distinction
                if mapped_row.get('distinction'):
                    distinction_str = str(mapped_row['distinction']).strip()
                    if distinction_str:
                        try:
                            # Try to parse as JSON array first
                            if distinction_str.startswith('[') and distinction_str.endswith(']'):
                                distinction_values = json.loads(distinction_str)
                                distinction_values = [float(v) for v in distinction_values if v is not None]
                            else:
                                # Parse as single value
                                distinction_val = float(distinction_str)
                                if distinction_val != 0:  # Only add non-zero values
                                    distinction_values = [distinction_val]
                        except (ValueError, json.JSONDecodeError):
                            pass
                
                # Apply N/A rule: only if both accuracy AND distinction have no values
                # (meaning both were 0 or empty in the original data)
                if not accuracy_values and not distinction_values:
                    # Check if original values were both 0 (not just empty)
                    orig_acc = mapped_row.get('accuracy', '').strip()
                    orig_dist = mapped_row.get('distinction', '').strip()
                    if orig_acc == '0' and orig_dist == '0':
                        # Both were explicitly 0, treat as N/A
                        accuracy_values = []
                        distinction_values = []
                
                # Build categories list
                categories = [mapped_row['category']]
                if mapped_row.get('category2'):
                    categories.append(mapped_row['category2'])
                if mapped_row.get('category3'):
                    categories.append(mapped_row['category3'])
                
                # Remove duplicates while preserving order
                unique_categories = []
                for cat in categories:
                    if cat and cat not in unique_categories:
                        unique_categories.append(cat)
                
                # Create question
                question = Question(
                    id=next_id,
                    category=unique_categories[0],
                    question=mapped_row['question'],
                    answer1=mapped_row['answer1'],
                    answer2=mapped_row['answer2'],
                    answer3=mapped_row['answer3'],
                    answer4=mapped_row['answer4'],
                    correct_answer_id=correct_answer_id,
                    source='uploaded',
                    uploaded_at=datetime.utcnow()
                )
                question.categories = unique_categories
                
                # Set performance values using the multiple values system
                question.accuracy_list = accuracy_values
                question.distinction_list = distinction_values
                
                db.session.add(question)
                questions_added += 1
                next_id += 1
                
            except Exception as e:
                errors.append(f"שורה {row_num}: {str(e)}")
        
        if questions_added > 0:
            db.session.commit()
            update_categories()
            
            if errors:
                return jsonify({
                    "success": True,
                    "message": f"הועלו {questions_added} שאלות בהצלחה",
                    "details": {"errors": errors}
                })
            else:
                return jsonify({
                    "success": True,
                    "message": f"הועלו {questions_added} שאלות בהצלחה"
                })
        else:
            db.session.rollback()
            return jsonify({
                "success": False,
                "message": "לא הועלו שאלות",
                "details": {"errors": errors}
            }), 400
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": f"שגיאה בהעלאת הקובץ: {str(e)}"}), 500

@upload_bp.route('/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a question"""
    try:
        question = Question.query.get(question_id)
        if not question:
            return jsonify({"error": "השאלה לא נמצאה"}), 404
        
        db.session.delete(question)
        db.session.commit()
        update_categories()
        
        return jsonify({"message": "השאלה נמחקה בהצלחה"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/questions/<int:question_id>', methods=['PUT'])
def update_question(question_id):
    """Update a question"""
    try:
        question = Question.query.get(question_id)
        if not question:
            return jsonify({"error": "השאלה לא נמצאה"}), 404
        
        data = request.get_json()
        
        # Update fields
        question.category = data.get('category', question.category)
        question.categories = data.get('categories', question.categories)
        question.question = data.get('question', question.question)
        question.answer1 = data.get('answer1', question.answer1)
        question.answer2 = data.get('answer2', question.answer2)
        question.answer3 = data.get('answer3', question.answer3)
        question.answer4 = data.get('answer4', question.answer4)
        question.correct_answer_id = data.get('correct_answer_id', question.correct_answer_id)
        question.accuracy = data.get('accuracy', question.accuracy)
        question.distinction = data.get('distinction', question.distinction)
        question.updated_at = datetime.utcnow()
        
        db.session.commit()
        update_categories()
        
        return jsonify(question.to_dict())
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/questions/<int:question_id>/add-category', methods=['POST'])
def add_secondary_category(question_id):
    """Add a secondary category to a question"""
    try:
        question = Question.query.get(question_id)
        if not question:
            return jsonify({"error": "השאלה לא נמצאה"}), 404
        
        data = request.get_json()
        new_category = data.get('category')
        
        if not new_category:
            return jsonify({"error": "חסרה קטגוריה"}), 400
        
        current_categories = question.categories
        if new_category in current_categories:
            return jsonify({"error": "הקטגוריה כבר קיימת"}), 400
        
        if len(current_categories) >= 3:
            return jsonify({"error": "ניתן להוסיף עד 3 קטגוריות לשאלה"}), 400
        
        current_categories.append(new_category)
        question.categories = current_categories
        question.updated_at = datetime.utcnow()
        
        db.session.commit()
        update_categories()
        
        return jsonify(question.to_dict())
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/questions/<int:question_id>/remove-category', methods=['DELETE'])
def remove_secondary_category(question_id):
    """Remove a secondary category from a question"""
    try:
        question = Question.query.get(question_id)
        if not question:
            return jsonify({"error": "השאלה לא נמצאה"}), 404
        
        data = request.get_json()
        category_to_remove = data.get('category')
        
        if not category_to_remove:
            return jsonify({"error": "חסרה קטגוריה"}), 400
        
        current_categories = question.categories
        if category_to_remove not in current_categories:
            return jsonify({"error": "הקטגוריה לא נמצאה"}), 400
        
        if len(current_categories) <= 1:
            return jsonify({"error": "לא ניתן להסיר את הקטגוריה היחידה"}), 400
        
        current_categories.remove(category_to_remove)
        question.categories = current_categories
        question.category = current_categories[0]  # Update primary category
        question.updated_at = datetime.utcnow()
        
        db.session.commit()
        update_categories()
        
        return jsonify(question.to_dict())
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/questions/<int:question_id>/duplicate', methods=['POST'])
def duplicate_question(question_id):
    """Duplicate a question"""
    try:
        original = Question.query.get(question_id)
        if not original:
            return jsonify({"error": "השאלה לא נמצאה"}), 404
        
        # Get the next available ID
        max_id = db.session.query(db.func.max(Question.id)).scalar() or 0
        next_id = max_id + 1
        
        # Create duplicate
        duplicate = Question(
            id=next_id,
            category=original.category,
            question=original.question,
            answer1=original.answer1,
            answer2=original.answer2,
            answer3=original.answer3,
            answer4=original.answer4,
            correct_answer_id=original.correct_answer_id,
            accuracy=original.accuracy,
            distinction=original.distinction,
            source=original.source,
            uploaded_at=datetime.utcnow()
        )
        duplicate.categories = original.categories
        
        db.session.add(duplicate)
        db.session.commit()
        update_categories()
        
        return jsonify({"message": "השאלה שוכפלה בהצלחה", "question": duplicate.to_dict()})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/download-template', methods=['GET'])
def download_template():
    """Download Excel template with example questions"""
    try:
        from openpyxl.styles import Font, PatternFill, Alignment
        
        # Create a new workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Template For Upload"
        
        # Hebrew headers
        headers = ['נושא', 'שאלה', 'תשובה1', 'תשובה2', 'תשובה3', 'תשובה4', 'תשובה_נכונה', 'דיוק', 'הבחנה', 'נושא2', 'נושא3']
        
        # Add headers with styling
        for col, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col, value=header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCCCCC", end_color="CCCCCC", fill_type="solid")
            cell.alignment = Alignment(horizontal="right")
        
        # Example questions data
        questions_data = [
            # Question 1: Empty measures
            [
                'מבוא',
                'איזה חלק במוח אחראי על הזיכרון לטווח קצר?',
                'ההיפוקמפוס',
                'הקורטקס הפרה-פרונטלי',
                'המוח הקטן',
                'גזע המוח',
                '1',
                '',  # Empty accuracy
                ''   # Empty distinction
            ],
            # Question 2: Single values
            [
                'היסטולוגיה',
                'איזה סוג תא עצבי מוליך אותות בין נוירונים שונים?',
                'נוירון מוטורי',
                'אינטרנוירון',
                'נוירון חושי',
                'תא גליה',
                '2',
                '85',    # Single accuracy value
                '0.45'   # Single distinction value
            ],
            # Question 3: Multiple values (JSON arrays)
            [
                'לוקליזציה פונקציונלית',
                'באיזה אזור בקורטקס נמצא המרכז המוטורי הראשוני?',
                'הגירוס הפרה-מרכזי',
                'הגירוס הפוסט-מרכזי',
                'האונה הפרונטלית',
                'האונה הטמפורלית',
                '1',
                '[93, 87, 91]',           # Multiple accuracy values
                '[0.62, 0.58, 0.65]'      # Multiple distinction values
            ]
        ]
        
        # Add example questions
        for row_idx, question_data in enumerate(questions_data, 2):
            for col_idx, value in enumerate(question_data, 1):
                cell = ws.cell(row=row_idx, column=col_idx, value=value)
                cell.alignment = Alignment(horizontal="right")
        
        # Auto-adjust column widths
        for column in ws.columns:
            max_length = 0
            column_letter = column[0].column_letter
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = min(max_length + 2, 50)
            ws.column_dimensions[column_letter].width = adjusted_width
        
        # Add instructions sheet
        instructions_ws = wb.create_sheet("הוראות שימוש")
        instructions_data = [
            ['הוראות שימוש בתבנית העלאת שאלות'],
            [''],
            ['עמודות חובה:'],
            ['נושא - קטגוריה של השאלה'],
            ['שאלה - טקסט השאלה'],
            ['תשובה1-4 - ארבע אפשרויות תשובה'],
            ['תשובה_נכונה - מספר התשובה הנכונה (1-4)'],
            [''],
            ['עמודות אופציונליות:'],
            ['דיוק - ציון דיוק (0-100) או מערך JSON עבור ערכים מרובים'],
            ['הבחנה - ציון הבחנה (0-1) או מערך JSON עבור ערכים מרובים'],
            [''],
            ['דוגמאות לפורמט נתוני ביצועים:'],
            ['ערך יחיד: 85, 0.45'],
            ['ערכים מרובים: [93, 87, 91], [0.62, 0.58, 0.65]'],
            ['ללא נתונים: השאירו ריק'],
            [''],
            ['הערות:'],
            ['- אם שני הערכים דיוק והבחנה הם 0, הם יוצגו כ-N/A'],
            ['- ערכים מרובים מאפשרים מעקב אחר ביצועים ממבחנים שונים'],
            ['- השתמשו בפורמט JSON עבור ערכים מרובים: [ערך1, ערך2, ערך3]']
        ]
        
        for row_idx, instruction in enumerate(instructions_data, 1):
            cell = instructions_ws.cell(row=row_idx, column=1, value=instruction[0])
            cell.alignment = Alignment(horizontal="right")
            if row_idx == 1:  # Title
                cell.font = Font(bold=True, size=14)
            elif instruction[0] in ['עמודות חובה:', 'עמודות אופציונליות:', 'דוגמאות לפורמט נתוני ביצועים:', 'הערות:']:
                cell.font = Font(bold=True)
        
        instructions_ws.column_dimensions['A'].width = 80
        
        # Save to BytesIO
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        # Create response
        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = 'attachment; filename="Template_For_Upload.xlsx"'
        
        return response
        
    except Exception as e:
        return jsonify({"error": f"שגיאה ביצירת התבנית: {str(e)}"}), 500

@upload_bp.route('/export-excel', methods=['GET'])
def export_excel():
    """Export all questions to Excel"""
    try:
        questions = Question.query.all()
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Questions Export"
        
        # Write Hebrew headers
        headers = ['נושא', 'שאלה', 'תשובה1', 'תשובה2', 'תשובה3', 'תשובה4', 'תשובה_נכונה', 'דיוק', 'הבחנה']
        
        # Add extra category columns if needed
        max_categories = max([len(q.categories) for q in questions], default=1)
        for i in range(2, max_categories + 1):
            headers.append(f'נושא{i}')
        
        # Write headers to Excel
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        
        # Write questions to Excel
        for row_idx, question in enumerate(questions, 2):
            # Format performance values as JSON arrays (even for single values)
            accuracy_export = ""
            distinction_export = ""
            
            # Get accuracy values
            acc_list = question.accuracy_list
            if acc_list:
                if len(acc_list) == 1:
                    accuracy_export = f"[{acc_list[0]}]"  # Single value in array format
                else:
                    accuracy_export = json.dumps(acc_list)  # Multiple values as JSON array
            
            # Get distinction values  
            dist_list = question.distinction_list
            if dist_list:
                if len(dist_list) == 1:
                    distinction_export = f"[{dist_list[0]}]"  # Single value in array format
                else:
                    distinction_export = json.dumps(dist_list)  # Multiple values as JSON array
            
            row_data = [
                question.category,
                question.question,
                question.answer1,
                question.answer2,
                question.answer3,
                question.answer4,
                question.correct_answer_id,
                accuracy_export,
                distinction_export
            ]
            
            # Add additional categories
            categories = question.categories
            for i in range(1, max_categories):
                if i < len(categories):
                    row_data.append(categories[i])
                else:
                    row_data.append('')
            
            # Write row to Excel
            for col, value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col, value=value)
        
        # Save to BytesIO
        excel_buffer = BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        
        # Create response
        response = make_response(excel_buffer.getvalue())
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename=questions_export_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        
        return response
        
    except Exception as e:
        print(f"Error in export_excel: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/clear-all', methods=['DELETE'])
def clear_all_questions():
    """Clear all questions and categories"""
    try:
        Question.query.delete()
        Category.query.delete()
        db.session.commit()
        
        return jsonify({"message": "כל השאלות נמחקו בהצלחה"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@upload_bp.route('/categories/<category_name>', methods=['PUT'])
def update_category_name(category_name):
    """Update category name"""
    try:
        data = request.get_json()
        new_name = data.get('new_name')
        
        if not new_name:
            return jsonify({"error": "חסר שם חדש לקטגוריה"}), 400
        
        # Update all questions with this category
        questions = Question.query.all()
        updated_count = 0
        
        for question in questions:
            categories = question.categories
            if category_name in categories:
                # Update the category in the list
                categories = [new_name if cat == category_name else cat for cat in categories]
                question.categories = categories
                
                # Update primary category if needed
                if question.category == category_name:
                    question.category = new_name
                
                question.updated_at = datetime.utcnow()
                updated_count += 1
        
        if updated_count > 0:
            db.session.commit()
            update_categories()
            return jsonify({"message": f"עודכנו {updated_count} שאלות"})
        else:
            return jsonify({"message": "לא נמצאו שאלות עם קטגוריה זו"})
            
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500



# Test Generation Endpoints

@upload_bp.route('/generate-test', methods=['POST'])
def generate_test():
    """Generate a test with specified questions from each category"""
    try:
        data = request.get_json()
        category_counts = data.get('category_counts', {})  # {category: count}
        exclude_questions = data.get('exclude_questions', [])  # List of question IDs to exclude
        
        # Validate total count
        total_requested = sum(category_counts.values())
        if total_requested == 0:
            return jsonify({'error': 'חייב לבחור לפחות שאלה אחת'}), 400
        
        selected_questions = []
        used_questions = []
        
        # Select questions from each category
        for category, count in category_counts.items():
            if count > 0:
                # Get questions from this category, excluding specified ones
                category_questions = Question.query.filter(
                    Question.categories.contains(category),
                    ~Question.id.in_(exclude_questions)
                ).all()
                
                if len(category_questions) < count:
                    return jsonify({
                        'error': f'לא מספיק שאלות בקטגוריה "{category}". זמינות: {len(category_questions)}, נדרשות: {count}'
                    }), 400
                
                # Randomly select the required number of questions
                import random
                selected = random.sample(category_questions, count)
                selected_questions.extend(selected)
                used_questions.extend([q.id for q in selected])
        
        # Shuffle the final question order
        random.shuffle(selected_questions)
        
        # Generate test content
        test_content = ""
        answer_sheet_content = ""
        
        for i, question in enumerate(selected_questions, 1):
            # Question text
            question_text = f"{i}. {question.question}\n"
            question_text += f"1. {question.answer1}\n"
            question_text += f"2. {question.answer2}\n"
            question_text += f"3. {question.answer3}\n"
            question_text += f"4. {question.answer4}\n\n"
            
            test_content += question_text
            
            # Answer sheet with correct answer highlighted
            answer_text = f"{i}. {question.question}\n"
            for j in range(1, 5):
                answer = getattr(question, f'answer{j}')
                if j == question.correct_answer_id:
                    answer_text += f"{j}. **{answer}** (נכון)\n"  # Mark correct answer
                else:
                    answer_text += f"{j}. {answer}\n"
            answer_text += "\n"
            
            answer_sheet_content += answer_text
        
        # Generate CSV tracking data
        csv_data = []
        for question in selected_questions:
            csv_data.append({
                'question_id': question.id,
                'category': question.category,
                'question': question.question,
                'correct_answer': question.correct_answer_id,
                'accuracy': question.accuracy,
                'distinction': question.distinction
            })
        
        return jsonify({
            'test_content': test_content,
            'answer_sheet_content': answer_sheet_content,
            'used_questions': used_questions,
            'csv_data': csv_data,
            'total_questions': len(selected_questions)
        })
        
    except Exception as e:
        return jsonify({'error': f'שגיאה ביצירת המבחן: {str(e)}'}), 500

@upload_bp.route('/categories-summary', methods=['GET'])
def get_categories_summary():
    """Get summary of all categories with question counts"""
    try:
        categories = Category.query.all()
        summary = []
        
        for category in categories:
            question_count = Question.query.filter(
                Question.categories.contains(category.name)
            ).count()
            
            summary.append({
                'name': category.name,
                'count': question_count
            })
        
        return jsonify(summary)
        
    except Exception as e:
        return jsonify({'error': f'שגיאה בקבלת סיכום קטגוריות: {str(e)}'}), 500

@upload_bp.route('/download-test-files', methods=['POST'])
def download_test_files():
    """Generate and download test files (test + answer sheet + CSV)"""
    try:
        data = request.get_json()
        test_content = data.get('test_content', '')
        answer_sheet_content = data.get('answer_sheet_content', '')
        csv_data = data.get('csv_data', [])
        
        # Create a zip file with all test materials
        import zipfile
        import tempfile
        import csv as csv_module
        from datetime import datetime
        
        # Create temporary directory
        with tempfile.TemporaryDirectory() as temp_dir:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            # Write test file
            test_file = os.path.join(temp_dir, f'test_{timestamp}.txt')
            with open(test_file, 'w', encoding='utf-8-sig') as f:
                f.write(test_content)
            
            # Write answer sheet
            answer_file = os.path.join(temp_dir, f'answer_sheet_{timestamp}.txt')
            with open(answer_file, 'w', encoding='utf-8-sig') as f:
                f.write(answer_sheet_content)
            
            # Write CSV tracking file
            csv_file = os.path.join(temp_dir, f'test_questions_{timestamp}.csv')
            with open(csv_file, 'w', encoding='utf-8-sig', newline='') as f:
                if csv_data:
                    writer = csv_module.DictWriter(f, fieldnames=csv_data[0].keys())
                    writer.writeheader()
                    writer.writerows(csv_data)
            
            # Create zip file
            zip_path = os.path.join(temp_dir, f'test_package_{timestamp}.zip')
            with zipfile.ZipFile(zip_path, 'w') as zip_file:
                zip_file.write(test_file, f'test_{timestamp}.txt')
                zip_file.write(answer_file, f'answer_sheet_{timestamp}.txt')
                zip_file.write(csv_file, f'test_questions_{timestamp}.csv')
            
            # Read zip file and return as response
            with open(zip_path, 'rb') as f:
                zip_data = f.read()
            
            response = make_response(zip_data)
            response.headers['Content-Type'] = 'application/zip'
            response.headers['Content-Disposition'] = f'attachment; filename=test_package_{timestamp}.zip'
            
            return response
            
    except Exception as e:
        return jsonify({'error': f'שגיאה ביצירת קבצי המבחן: {str(e)}'}), 500

