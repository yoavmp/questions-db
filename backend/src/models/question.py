from src.models.user import db
from datetime import datetime
import json

class Question(db.Model):
    __tablename__ = 'questions'
    
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(200), nullable=False)
    categories_json = db.Column(db.Text)  # Store multiple categories as JSON
    question = db.Column(db.Text, nullable=False)
    answer1 = db.Column(db.Text, nullable=False)
    answer2 = db.Column(db.Text, nullable=False)
    answer3 = db.Column(db.Text, nullable=False)
    answer4 = db.Column(db.Text, nullable=False)
    correct_answer_id = db.Column(db.Integer, nullable=False)
    
    # Store multiple performance values as JSON arrays
    accuracy_values = db.Column(db.Text, default='[]')  # JSON array of accuracy values
    distinction_values = db.Column(db.Text, default='[]')  # JSON array of distinction values
    
    source = db.Column(db.String(50), default='uploaded')
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Question {self.id}: {self.question[:50]}...>'

    @property
    def accuracy_list(self):
        """Get list of accuracy values"""
        try:
            values = json.loads(self.accuracy_values or '[]')
            return [float(v) for v in values if v is not None]
        except:
            return []
    
    @accuracy_list.setter
    def accuracy_list(self, values):
        """Set list of accuracy values"""
        clean_values = [float(v) for v in values if v is not None]
        self.accuracy_values = json.dumps(clean_values)
    
    @property
    def distinction_list(self):
        """Get list of distinction values"""
        try:
            values = json.loads(self.distinction_values or '[]')
            return [float(v) for v in values if v is not None]
        except:
            return []
    
    @distinction_list.setter
    def distinction_list(self, values):
        """Set list of distinction values"""
        clean_values = [float(v) for v in values if v is not None]
        self.distinction_values = json.dumps(clean_values)
    
    @property
    def accuracy(self):
        """Get average accuracy or None if no values"""
        values = self.accuracy_list
        return sum(values) / len(values) if values else None
    
    @property
    def distinction(self):
        """Get average distinction or None if no values"""
        values = self.distinction_list
        return sum(values) / len(values) if values else None

    @property
    def categories(self):
        """Get categories as a list"""
        if self.categories_json:
            try:
                return json.loads(self.categories_json)
            except:
                return [self.category]
        return [self.category]

    @categories.setter
    def categories(self, value):
        """Set categories from a list"""
        if isinstance(value, list):
            self.categories_json = json.dumps(value, ensure_ascii=False)
            if value:
                self.category = value[0]  # Primary category is the first one
        else:
            self.category = value
            self.categories_json = json.dumps([value], ensure_ascii=False)

    def add_performance_data(self, accuracy, distinction):
        """Add new performance data to existing values"""
        acc_list = self.accuracy_list
        dist_list = self.distinction_list
        
        if accuracy is not None:
            acc_list.append(float(accuracy))
            self.accuracy_list = acc_list
            
        if distinction is not None:
            dist_list.append(float(distinction))
            self.distinction_list = dist_list

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'categories': self.categories,
            'question': self.question,
            'answer1': self.answer1,
            'answer2': self.answer2,
            'answer3': self.answer3,
            'answer4': self.answer4,
            'correct_answer_id': self.correct_answer_id,
            'accuracy': self.accuracy,  # Average accuracy
            'distinction': self.distinction,  # Average distinction
            'accuracy_list': self.accuracy_list,  # All accuracy values
            'distinction_list': self.distinction_list,  # All distinction values
            'source': self.source,
            'uploaded_at': self.uploaded_at.isoformat() if self.uploaded_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    @classmethod
    def from_dict(cls, data):
        """Create a Question instance from dictionary data"""
        question = cls()
        question.category = data.get('category', '')
        question.categories = data.get('categories', [data.get('category', '')])
        question.question = data.get('question', '')
        question.answer1 = data.get('answer1', '')
        question.answer2 = data.get('answer2', '')
        question.answer3 = data.get('answer3', '')
        question.answer4 = data.get('answer4', '')
        question.correct_answer_id = data.get('correct_answer_id', 1)
        question.source = data.get('source', 'uploaded')
        
        # Handle performance values - treat as N/A only if both are 0
        accuracy = data.get('accuracy')
        distinction = data.get('distinction')
        
        if accuracy is not None and distinction is not None and not (accuracy == 0 and distinction == 0):
            if accuracy != 0:
                question.accuracy_list = [accuracy]
            if distinction != 0:
                question.distinction_list = [distinction]
        elif accuracy is not None and accuracy != 0:
            question.accuracy_list = [accuracy]
        elif distinction is not None and distinction != 0:
            question.distinction_list = [distinction]
        
        # Handle datetime fields
        if 'uploaded_at' in data and data['uploaded_at']:
            try:
                question.uploaded_at = datetime.fromisoformat(data['uploaded_at'].replace('Z', '+00:00'))
            except:
                question.uploaded_at = datetime.utcnow()
        
        return question


class Category(db.Model):
    __tablename__ = 'categories'
    
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    question_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Category {self.name}: {self.question_count} questions>'

    def to_dict(self):
        return {
            'name': self.name,
            'question_count': self.question_count
        }

