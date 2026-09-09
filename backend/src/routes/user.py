from flask import Blueprint, jsonify
from src.models.user import db
from src.models.question import Question, Category
from src.utils.category_order import sort_categories

user_bp = Blueprint('user', __name__)

@user_bp.route('/questions', methods=['GET'])
def get_questions():
    """Get all questions"""
    try:
        questions = Question.query.all()
        return jsonify([question.to_dict() for question in questions])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/categories', methods=['GET'])
def get_categories():
    """Get all categories with question counts, sorted by predefined order"""
    try:
        categories = Category.query.all()
        categories_data = [category.to_dict() for category in categories]
        
        # Extract category names and sort them
        category_names = [cat['name'] for cat in categories_data]
        sorted_names = sort_categories(category_names)
        
        # Reorder categories_data according to sorted names
        sorted_categories = []
        for name in sorted_names:
            for cat_data in categories_data:
                if cat_data['name'] == name:
                    sorted_categories.append(cat_data)
                    break
        
        return jsonify(sorted_categories)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@user_bp.route('/questions/<int:question_id>', methods=['PUT'])
def update_question(question_id):
    """Update a question"""
    try:
        from flask import request
        data = request.get_json()
        
        question = Question.query.get_or_404(question_id)
        
        # Update question fields
        question.question = data.get('question', question.question)
        question.answer1 = data.get('answer1', question.answer1)
        question.answer2 = data.get('answer2', question.answer2)
        question.answer3 = data.get('answer3', question.answer3)
        question.answer4 = data.get('answer4', question.answer4)
        question.correct_answer_id = data.get('correct_answer_id', question.correct_answer_id)
        
        db.session.commit()
        
        return jsonify(question.to_dict())
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@user_bp.route('/questions/<int:question_id>/add-performance', methods=['POST'])
def add_performance_data(question_id):
    """Add performance data to a question"""
    try:
        from flask import request
        data = request.get_json()
        accuracy = data.get('accuracy')
        distinction = data.get('distinction')
        
        question = Question.query.get_or_404(question_id)
        
        # Validate input
        if accuracy is not None:
            try:
                accuracy = float(accuracy)
                if not (0 <= accuracy <= 100):
                    return jsonify({"error": "דיוק חייב להיות בין 0 ל-100"}), 400
            except ValueError:
                return jsonify({"error": "ערך דיוק לא תקין"}), 400
                
        if distinction is not None:
            try:
                distinction = float(distinction)
                if not (0 <= distinction <= 1):
                    return jsonify({"error": "הבחנה חייבת להיות בין 0 ל-1"}), 400
            except ValueError:
                return jsonify({"error": "ערך הבחנה לא תקין"}), 400
        
        # Add performance data
        question.add_performance_data(accuracy, distinction)
        db.session.commit()
        
        return jsonify({
            "message": "נתוני ביצועים נוספו בהצלחה",
            "question": question.to_dict()
        })
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

@user_bp.route('/questions/<int:question_id>', methods=['DELETE'])
def delete_question(question_id):
    """Delete a question"""
    try:
        question = Question.query.get_or_404(question_id)
        
        # Update category count
        category = Category.query.filter_by(name=question.category).first()
        if category:
            category.question_count = max(0, category.question_count - 1)
            if category.question_count == 0:
                db.session.delete(category)
        
        db.session.delete(question)
        db.session.commit()
        
        return jsonify({"message": "השאלה נמחקה בהצלחה"})
        
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500
