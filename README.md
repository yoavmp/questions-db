# מאגר שאלות בחינה בעברית - Hebrew Exam Questions System

A comprehensive web-based system for managing Hebrew exam questions with multiple performance values tracking, Excel import/export, and test generation capabilities.

## 🌟 Features

- **Hebrew RTL Support**: Full right-to-left text support with proper Hebrew rendering
- **Excel Integration**: Import and export questions using Excel files (.xlsx)
- **Multiple Performance Values**: Track accuracy (דיוק) and distinction (הבחנה) from multiple exams
- **Test Generation**: Create randomized tests with category-based selection
- **Question Management**: Add, edit, delete, and categorize questions
- **Performance Analytics**: Calculate averages and statistics from historical data
- **Responsive Design**: Works on desktop and mobile devices

## 📋 System Requirements

### Backend Requirements
- Python 3.11 or higher
- pip (Python package manager)

### Frontend Requirements
- Node.js 18+ 
- npm or yarn

## 🚀 Quick Start

### 0. Clone with submodules

The Hebrew neuroanatomy question generator lives in the **`exam_generator/`
Git submodule** (independent repository
`https://github.com/yoavmp/exam-generator.git`, pinned to a verified commit).
Clone the parent with its submodule in one step:

```bash
git clone --recurse-submodules https://github.com/yoavmp/questions-db.git
```

If you already cloned without `--recurse-submodules`:

```bash
git submodule update --init --recursive
```

To move the submodule to the commit this repository currently pins (e.g. after
`git pull`):

```bash
git submodule update --init --recursive
```

The parent repository tracks only `.gitmodules` and the `exam_generator`
gitlink — never the generator's individual files. Do not commit or push inside
`exam_generator/`; it is updated on its own and re-pinned here by a dedicated
integration work package. Its course material under `exam_generator/Data/` is
git-ignored runtime input supplied out of band.

### 1. Backend Setup

```bash
# Navigate to backend directory
cd backend

# Create virtual environment
python3 -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the backend server
python run.py
```

The backend will start on `http://localhost:4567`

### 2. Frontend Setup

```bash
# Navigate to frontend directory (in a new terminal)
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev
```

The frontend will start on `http://localhost:3000`

## 📊 Excel Template Format

The system uses Excel files with the following Hebrew headers:

| נושא | שאלה | תשובה1 | תשובה2 | תשובה3 | תשובה4 | תשובה_נכונה | דיוק | הבחנה |
|------|------|--------|--------|--------|--------|-------------|------|-------|
| Category | Question | Answer1 | Answer2 | Answer3 | Answer4 | Correct Answer (1-4) | Accuracy (0-100) | Distinction (0-1) |

### Performance Data Types:
1. **No Values**: Leave accuracy and distinction fields empty
2. **Single Values**: Enter numeric values (e.g., 85, 0.45)
3. **Multiple Values**: Enter JSON arrays (e.g., [93, 87, 91], [0.62, 0.58, 0.65])

## 🔧 API Endpoints

### Questions Management
- `GET /api/questions` - Get all questions
- `POST /api/upload-excel` - Upload questions from Excel
- `GET /api/export-excel` - Export questions to Excel
- `PUT /api/questions/{id}` - Update question
- `DELETE /api/questions/{id}` - Delete question
- `POST /api/questions/{id}/add-performance` - Add performance data

### Test Generation
- `POST /api/generate-test` - Generate test with specified criteria
- `POST /api/generate-docx` - Generate test document
- `POST /api/generate-tracking-excel` - Generate tracking Excel

### Categories
- `GET /api/categories` - Get all categories
- `DELETE /api/clear-all` - Clear all questions

## 📁 Project Structure

```
hebrew-exam-system/
├── backend/
│   ├── src/
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── user.py          # Database configuration
│   │   │   └── question.py      # Question and Category models
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── user.py          # User routes
│   │   │   ├── upload.py        # File upload/export routes
│   │   │   └── test_generation.py # Test generation routes
│   │   └── main.py              # Flask application setup
│   ├── requirements.txt         # Python dependencies
│   └── run.py                   # Application entry point
├── frontend/
│   ├── src/
│   │   ├── components/ui/       # UI components
│   │   ├── App.jsx              # Main React application
│   │   ├── App.css              # Styles with Hebrew RTL support
│   │   └── main.jsx             # React entry point
│   ├── package.json             # Node.js dependencies
│   ├── vite.config.js           # Vite configuration
│   ├── tailwind.config.js       # Tailwind CSS configuration
│   └── index.html               # HTML template
└── README.md                    # This file
```

## 🗄️ Database Schema

The system uses SQLite with the following main tables:

### Questions Table
- `id`: Primary key
- `category`: Question category
- `question`: Question text
- `answer1-4`: Four answer options
- `correct_answer_id`: Correct answer (1-4)
- `accuracy`: Single accuracy value (for backward compatibility)
- `distinction`: Single distinction value (for backward compatibility)
- `accuracy_values`: JSON array of multiple accuracy values
- `distinction_values`: JSON array of multiple distinction values
- `upload_date`: Upload timestamp
- `categories_json`: JSON array for multiple categories

### Categories Table
- `id`: Primary key
- `name`: Category name
- `question_count`: Number of questions in category

## 🎯 Multiple Performance Values

The system supports tracking performance data from multiple exams:

### Adding Performance Data
1. Edit a question in the interface
2. Click "הוסף נתוני ביצועים" (Add Performance Data)
3. Enter new accuracy (0-100%) and/or distinction (0-1) values
4. Values are stored alongside existing data

### Display Format
- Single values: "דיוק: 85%"
- Multiple values: "דיוק: 93%, 87%, 91%"
- Averages used for test statistics

## 🔒 N/A Value Rules

Performance values are treated as N/A (missing) only when:
- Both accuracy AND distinction are 0 for the same question
- Individual 0 values are kept as valid data points

## 🌐 Production Deployment

For production deployment:
1. Build the frontend: `npm run build`
2. Configure backend for production environment
3. Set up proper database (PostgreSQL recommended)
4. Configure CORS for your domain
5. Use a production WSGI server (gunicorn included)

## 🛠️ Development

### Backend Development
- Flask with SQLAlchemy ORM
- CORS enabled for frontend communication
- Excel processing with openpyxl
- DOCX generation with python-docx

### Frontend Development
- React with modern hooks
- Tailwind CSS for styling
- Hebrew RTL support
- Responsive design
- Custom UI components

## 📝 License

This project is developed for educational purposes.

## 🤝 Support

For questions or issues, please refer to the system documentation or contact the development team.

---

**מערכת ניהול שאלות בחינה בעברית - Hebrew Exam Questions Management System**

