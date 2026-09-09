import json
import openpyxl
from flask import Blueprint, request, jsonify
from src.models.question import Question

exclusion_bp = Blueprint('exclusion', __name__)

@exclusion_bp.route('/test/upload-exclusion', methods=['POST'])
def upload_exclusion_file():
    """Upload and parse exclusion file to extract question IDs"""
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
            
            # Get headers
            headers = []
            for cell in worksheet[1]:
                headers.append(cell.value if cell.value else "")
            
            # Find the question ID column
            id_column_index = None
            question_column_index = None
            category_column_index = None
            
            # Look for Hebrew headers
            for i, header in enumerate(headers):
                header_str = str(header).strip()
                if header_str in ['מזהה_שאלה', 'id']:
                    id_column_index = i
                elif header_str in ['שאלה', 'question']:
                    question_column_index = i
                elif header_str in ['נושא', 'קטגוריה', 'category']:
                    category_column_index = i
            
            excluded_question_ids = []
            matched_questions = []
            
            # Process each row
            for row_num, row in enumerate(worksheet.iter_rows(min_row=2, values_only=True), start=2):
                if not any(cell is not None for cell in row):  # Skip empty rows
                    continue
                
                question_id = None
                question_text = None
                category = None
                
                # Extract data from row
                if id_column_index is not None and id_column_index < len(row):
                    try:
                        question_id = int(row[id_column_index]) if row[id_column_index] is not None else None
                    except (ValueError, TypeError):
                        pass
                
                if question_column_index is not None and question_column_index < len(row):
                    question_text = str(row[question_column_index]).strip() if row[question_column_index] is not None else None
                
                if category_column_index is not None and category_column_index < len(row):
                    category = str(row[category_column_index]).strip() if row[category_column_index] is not None else None
                
                # Try to match question by ID first
                if question_id:
                    question = Question.query.get(question_id)
                    if question:
                        excluded_question_ids.append(question_id)
                        matched_questions.append({
                            'id': question_id,
                            'question': question.question,
                            'category': question.category,
                            'match_method': 'id'
                        })
                        continue
                
                # If no ID match, try to match by question text and category
                if question_text and category:
                    question = Question.query.filter(
                        Question.question.like(f"%{question_text}%"),
                        Question.category == category
                    ).first()
                    
                    if question:
                        excluded_question_ids.append(question.id)
                        matched_questions.append({
                            'id': question.id,
                            'question': question.question,
                            'category': question.category,
                            'match_method': 'text_and_category'
                        })
                        continue
                
                # If still no match, try question text only
                if question_text:
                    question = Question.query.filter(
                        Question.question.like(f"%{question_text}%")
                    ).first()
                    
                    if question:
                        excluded_question_ids.append(question.id)
                        matched_questions.append({
                            'id': question.id,
                            'question': question.question,
                            'category': question.category,
                            'match_method': 'text_only'
                        })
            
            # Remove duplicates
            excluded_question_ids = list(set(excluded_question_ids))
            
            return jsonify({
                "success": True,
                "excluded_question_ids": excluded_question_ids,
                "matched_questions": matched_questions,
                "total_excluded": len(excluded_question_ids),
                "message": f"זוהו {len(excluded_question_ids)} שאלות להחרגה"
            })
            
        except Exception as e:
            return jsonify({"error": f"שגיאה בקריאת קובץ Excel: {str(e)}"}), 400
            
    except Exception as e:
        return jsonify({"error": f"שגיאה בהעלאת הקובץ: {str(e)}"}), 500
