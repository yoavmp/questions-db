import csv
import json
import random
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, make_response
from src.models.user import db
from src.models.question import Question, Category
from src.utils.category_order import sort_questions_by_category, group_questions_by_category
import openpyxl
from openpyxl import Workbook
from io import BytesIO

test_gen_bp = Blueprint('test_generation', __name__)

@test_gen_bp.route('/test/categories', methods=['GET'])
def get_test_categories():
    """Get all categories with their question counts for test generation"""
    try:
        categories = Category.query.filter(Category.name != "כל השאלות").all()
        return jsonify([{
            'name': c.name,
            'question_count': c.question_count
        } for c in categories])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@test_gen_bp.route('/test/generate', methods=['POST'])
def generate_test():
    """Generate a test based on category selections"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({"error": "נתונים חסרים"}), 400
        
        category_selections = data.get('categories', {})
        exclude_questions = data.get('exclude_questions', [])
        
        # Debug logging
        print(f"DEBUG: Received exclude_questions: {exclude_questions}")
        print(f"DEBUG: Type of exclude_questions: {type(exclude_questions)}")
        print(f"DEBUG: Length of exclude_questions: {len(exclude_questions)}")
        
        if not category_selections:
            return jsonify({"error": "יש לבחור לפחות קטגוריה אחת"}), 400
        
        # Validate total questions
        total_requested = sum(category_selections.values())
        if total_requested <= 0:
            return jsonify({"error": "יש לבחור לפחות שאלה אחת"}), 400
        
        selected_questions = []
        
        # Select questions from each category
        for category_name, num_questions in category_selections.items():
            if num_questions <= 0:
                continue
                
            # Get all questions from this category
            # Check both primary category and categories JSON
            category_questions = Question.query.filter(
                db.or_(
                    Question.category == category_name,
                    Question.categories_json.like(f'%"{category_name}"%')
                )
            ).all()
            
            # Filter out excluded questions
            print(f"DEBUG: Category '{category_name}' - Total questions: {len(category_questions)}")
            print(f"DEBUG: Category '{category_name}' - Question IDs: {[q.id for q in category_questions]}")
            
            available_questions = [
                q for q in category_questions 
                if q.id not in exclude_questions
            ]
            
            print(f"DEBUG: Category '{category_name}' - Available after exclusion: {len(available_questions)}")
            print(f"DEBUG: Category '{category_name}' - Available IDs: {[q.id for q in available_questions]}")
            excluded_count = len(category_questions) - len(available_questions)
            print(f"DEBUG: Category '{category_name}' - Excluded count: {excluded_count}")
            
            if len(available_questions) < num_questions:
                return jsonify({
                    "error": f"לא מספיק שאלות זמינות בקטגוריה '{category_name}'. זמינות: {len(available_questions)}, נדרשות: {num_questions}"
                }), 400
            
            # Randomly select the required number of questions
            selected = random.sample(available_questions, num_questions)
            selected_questions.extend(selected)
        
        # Sort questions by category instead of random shuffle
        selected_questions = sort_questions_by_category(selected_questions)
        
        # Convert to dict format for response
        test_questions = []
        for i, question in enumerate(selected_questions, 1):
            test_questions.append({
                'number': i,
                'id': question.id,
                'question': question.question,
                'answer1': question.answer1,
                'answer2': question.answer2,
                'answer3': question.answer3,
                'answer4': question.answer4,
                'correct_answer': question.correct_answer_id,
                'category': question.category,  # Add category for frontend grouping
                'categories': question.categories,
                'accuracy': question.accuracy,
                'distinction': question.distinction
            })
        
        return jsonify({
            'questions': test_questions,
            'total_questions': len(test_questions),
            'generation_time': datetime.now().isoformat()
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@test_gen_bp.route('/test/export-docx', methods=['POST'])
def export_test_docx():
    """Export test as DOCX file"""
    try:
        data = request.get_json()
        
        if not data or 'questions' not in data:
            return jsonify({"error": "נתונים חסרים"}), 400
        
        questions = data['questions']
        include_answers = data.get('include_answers', False)
        
        # Create DOCX content
        docx_content = generate_docx_content(questions, include_answers)
        
        # Create response
        response = make_response(docx_content)
        
        # Set headers for file download
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_suffix = "_with_answers" if include_answers else ""
        filename = f"test_exam{filename_suffix}_{timestamp}.docx"
        
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@test_gen_bp.route('/test/export-excel', methods=['POST'])
def export_test_excel():
    """Export test questions data as Excel for tracking"""
    try:
        data = request.get_json()
        
        if not data or 'questions' not in data:
            return jsonify({"error": "נתונים חסרים"}), 400
        
        questions = data['questions']
        
        # Create Excel workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Test Questions"
        
        # Hebrew headers
        headers = [
            'מספר_שאלה', 'מזהה_שאלה', 'נושא', 'שאלה', 'תשובה1', 'תשובה2', 
            'תשובה3', 'תשובה4', 'תשובה_נכונה', 'דיוק', 'הבחנה', 'תאריך_יצירה'
        ]
        
        # Write headers
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        
        generation_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Write data rows
        for row_idx, question in enumerate(questions, 2):
            # Get primary category (first one)
            primary_category = question['categories'][0] if question['categories'] else ''
            
            # Format performance values as JSON arrays (consistent with export format)
            accuracy_export = ""
            distinction_export = ""
            
            # Handle accuracy - check if it's a list or single value
            if 'accuracy_list' in question and question['accuracy_list']:
                acc_list = question['accuracy_list']
                if len(acc_list) == 1:
                    accuracy_export = f"[{acc_list[0]}]"  # Single value in array format
                else:
                    accuracy_export = json.dumps(acc_list)  # Multiple values as JSON array
            elif question.get('accuracy') is not None:
                # Fallback to single accuracy value
                accuracy_export = f"[{question['accuracy']}]"
            
            # Handle distinction - check if it's a list or single value
            if 'distinction_list' in question and question['distinction_list']:
                dist_list = question['distinction_list']
                if len(dist_list) == 1:
                    distinction_export = f"[{dist_list[0]}]"  # Single value in array format
                else:
                    distinction_export = json.dumps(dist_list)  # Multiple values as JSON array
            elif question.get('distinction') is not None:
                # Fallback to single distinction value
                distinction_export = f"[{question['distinction']}]"
            
            row_data = [
                question['number'],
                question['id'],
                primary_category,
                question['question'],
                question['answer1'],
                question['answer2'],
                question['answer3'],
                question['answer4'],
                question['correct_answer'],
                accuracy_export,
                distinction_export,
                generation_time
            ]
            
            for col, value in enumerate(row_data, 1):
                ws.cell(row=row_idx, column=col, value=value)
        
        # Save to BytesIO
        excel_buffer = BytesIO()
        wb.save(excel_buffer)
        excel_buffer.seek(0)
        
        # Create response
        response = make_response(excel_buffer.getvalue())
        
        # Set headers for file download
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"test_questions_tracking_{timestamp}.xlsx"
        
        response.headers['Content-Type'] = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def generate_docx_content(questions, include_answers=False):
    """Generate DOCX content for the test"""
    try:
        from docx import Document
        from docx.shared import Inches, Pt, RGBColor
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.enum.dml import MSO_THEME_COLOR_INDEX
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        
        def set_run_rtl(run):
            """Force a run to be RTL (like <w:rtl/>)"""
            r = run._element
            rPr = r.get_or_add_rPr()
            rtl = OxmlElement('w:rtl')
            rPr.append(rtl)

        def set_paragraph_bidi(paragraph):
            """Force paragraph <w:bidi/>"""
            p = paragraph._element
            pPr = p.get_or_add_pPr()
            bidi = OxmlElement('w:bidi')
            pPr.append(bidi)
        
        doc = Document()
        
        # Set document language and direction for Hebrew
        doc.core_properties.language = 'he-IL'
        
        # Configure document for RTL
        sections = doc.sections
        for section in sections:
            section.page_height = Inches(11.69)  # A4 height
            section.page_width = Inches(8.27)    # A4 width
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
        
        # Add questions
        for i, question in enumerate(questions):
            # Question number and text
            question_p = doc.add_paragraph()
            question_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            question_p.paragraph_format.left_indent = Inches(0)  # No indentation for questions
            set_paragraph_bidi(question_p)   # <w:bidi/>
            
            # Add question number and text with proper formatting
            run = question_p.add_run(f"{question['number']}. {question['question']}")
            run.font.size = Pt(12)  # David 12 font size
            run.font.name = 'David'  # Changed to David font
            run.bold = True
            set_run_rtl(run)   # <w:rtl/>
            
            # Add some space after question
            question_p.paragraph_format.space_after = Pt(6)
            
            # Add answer options
            answers = [
                (question['answer1'], 1),
                (question['answer2'], 2),
                (question['answer3'], 3),
                (question['answer4'], 4)
            ]

            # Create a daily seed based on today's date
            today = datetime.now().strftime("%Y%m%d")   # e.g., "20251130"
            daily_seed = int(today)

            random.seed(daily_seed + i) # Different shuffle for each question's answers

            # Shuffle in-place
            random.shuffle(answers)
            
            # Hebrew alphabet for answer options
            hebrew_letters = ['א', 'ב', 'ג', 'ד']
            
            for j, (answer_text, original_pos) in enumerate(answers):
                answer_p = doc.add_paragraph()
                answer_p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
                answer_p.paragraph_format.left_indent = Inches(0.5)  # Increased indentation for answers
                answer_p.paragraph_format.space_after = Pt(3)
                set_paragraph_bidi(answer_p)   # <w:bidi/>
                
                answer_run = answer_p.add_run(f"{hebrew_letters[j]}. {answer_text}")
                answer_run.font.size = Pt(12)  # David 12 font size
                answer_run.font.name = 'David'  # Changed to David font
                set_run_rtl(answer_run)   # <w:rtl/>
                
                # Highlight entire correct answer line if requested
                if include_answers and original_pos == int(question['correct_answer']):
                    # Highlight the entire line with yellow
                    answer_run.font.highlight_color = 7  # Yellow highlight
                    # Remove bold formatting, just use highlighting
            
            # Add minimal spacing between questions for continuous blocks
            if i < len(questions) - 1:
                spacing_p = doc.add_paragraph()
                spacing_p.paragraph_format.space_after = Pt(6)  # Reduced spacing
                set_paragraph_bidi(spacing_p)   # <w:bidi/>
        
        # Save to bytes with proper encoding
        doc_io = io.BytesIO()
        doc.save(doc_io)
        doc_io.seek(0)
        
        return doc_io.getvalue()
        
    except Exception as e:
        # Enhanced fallback: create a simple but properly formatted text file
        print(f"DOCX generation error: {e}")
        content = "מבחן בעברית\n\n"
        
        hebrew_letters = ['א', 'ב', 'ג', 'ד']
        
        for question in questions:
            content += f"{question['number']}. {question['question']}\n\n"
            content += f"{hebrew_letters[0]}. {question['answer1']}\n"
            content += f"{hebrew_letters[1]}. {question['answer2']}\n"
            content += f"{hebrew_letters[2]}. {question['answer3']}\n"
            content += f"{hebrew_letters[3]}. {question['answer4']}\n"
            
            if include_answers:
                correct_idx = int(question['correct_answer']) - 1
                content += f"\nתשובה נכונה: {hebrew_letters[correct_idx]}\n"
            
            content += "\n"  # Simple spacing between questions
        
        return content.encode('utf-8-sig')



@test_gen_bp.route('/test/replace-question', methods=['POST'])
def replace_question():
    """Replace a question in the test with another from the same category"""
    try:
        data = request.get_json()
        question_id = data.get('question_id')
        category_name = data.get('category')
        exclude_questions = data.get('exclude_questions', [])
        current_test_questions = data.get('current_test_questions', [])
        
        if not question_id or not category_name:
            return jsonify({"error": "חסרים פרמטרים נדרשים"}), 400
        
        # Get all current question IDs to exclude them
        current_question_ids = [q['id'] for q in current_test_questions]
        all_excluded = set(exclude_questions + current_question_ids)
        
        # Find questions from the same category
        category_questions = Question.query.filter(
            db.or_(
                Question.category == category_name,
                Question.categories_json.like(f'%"{category_name}"%')
            )
        ).all()
        
        # Filter out excluded questions and current test questions
        available_questions = [
            q for q in category_questions 
            if q.id not in all_excluded
        ]
        
        if not available_questions:
            return jsonify({
                "error": f"אין שאלות זמינות נוספות בקטגוריה '{category_name}'"
            }), 400
        
        # Randomly select one replacement question
        replacement_question = random.choice(available_questions)
        
        # Convert to dict format for response
        replacement_data = {
            'id': replacement_question.id,
            'question': replacement_question.question,
            'answer1': replacement_question.answer1,
            'answer2': replacement_question.answer2,
            'answer3': replacement_question.answer3,
            'answer4': replacement_question.answer4,
            'correct_answer': replacement_question.correct_answer_id,
            'categories': replacement_question.categories,
            'accuracy': replacement_question.accuracy,
            'distinction': replacement_question.distinction
        }
        
        return jsonify({
            'replacement_question': replacement_data,
            'original_question_id': question_id
        })
        
    except Exception as e:
        print(f"Error replacing question: {e}")
        return jsonify({"error": "שגיאה בהחלפת השאלה"}), 500

