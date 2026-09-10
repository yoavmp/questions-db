import os
import sys
# DON'T CHANGE THIS !!!
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flask import Flask, send_from_directory
from flask_cors import CORS
from src.models.user import db
from src.models.question import Question, Category
from src.routes.user import user_bp
from src.routes.upload import upload_bp
from src.routes.test_generation import test_gen_bp
from src.routes.exclusion_upload import exclusion_bp

app = Flask(__name__, static_folder=os.path.join(os.path.dirname(__file__), 'static'))
app.config['SECRET_KEY'] = 'asdf#FGSgvasgf$5$WGT'

# Enable CORS for all routes
CORS(app, origins='*', 
     methods=['GET', 'POST', 'PUT', 'DELETE', 'OPTIONS'],
     allow_headers=['Content-Type', 'Authorization'])

# Register blueprints
app.register_blueprint(user_bp, url_prefix='/api')
app.register_blueprint(upload_bp, url_prefix='/api')
app.register_blueprint(test_gen_bp, url_prefix='/api')
app.register_blueprint(exclusion_bp, url_prefix='/api')

# Database configuration - use test database if TESTING environment variable is set
db_filename = 'app_test.db' if os.environ.get('TESTING') == 'true' else 'app.db'
app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(os.path.dirname(__file__), 'database', db_filename)}"
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database (use the same instance from user.py)
db.init_app(app)

with app.app_context():
    db.create_all()
    
    # Migrate existing JSON data to database if it exists
    from src.routes.upload import migrate_json_to_db
    migrate_json_to_db()

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def serve(path):
    static_folder_path = app.static_folder
    if static_folder_path is None:
            return "Static folder not configured", 404

    if path != "" and os.path.exists(os.path.join(static_folder_path, path)):
        return send_from_directory(static_folder_path, path)
    else:
        index_path = os.path.join(static_folder_path, 'index.html')
        if os.path.exists(index_path):
            return send_from_directory(static_folder_path, 'index.html')
        else:
            return "Hebrew Exam System Backend is running", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=4567, debug=True)

