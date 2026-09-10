# Running Backend
## Open terminal window #1
### Go to the backend directory:
cd /Volumes/homes/Yoav/Lab/Exam_Questions_Website/App_Deployment/Final_App/backend
### Open your virtual environment (venv):
source idoVenv/bin/activate # Ido's mac
source venv/bin/activate # Yoav's mac
source michalVenv/bin/activate # Michal's mac
### Run server:
python run.py
** This runs the server in development mode (with debugging)

#Running Frontend 
## Open terminal window #2
### go to the frontend directory:
cd /Volumes/homes/Yoav/Lab/Exam_Questions_Website/App_Deployment/Final_App/frontend
### Run the frontend and link to browser:
npm run dev
** This runs in development mode

## Now you can access the website by browsing to:
http://localhost:3000/

If something doesnt work - make sure python 3.11 (or higher) is installed.
