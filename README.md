Employee Attendance & Analytics API

A backend REST API built using Python, FastAPI, and MongoDB to manage employee records, track attendance, and generate attendance analytics.

Features

- Employee Management: Create and retrieve employee records with pagination.
- Attendance Tracking: Record employee punch-in and punch-out times.
- Attendance Rules: Calculate late arrivals, work hours, overtime, and half-day status.
- Attendance History: Retrieve and update attendance records.
- Monthly Analytics: View employee attendance statistics for a selected month.
- Department Analytics: Summarize attendance and work-hour statistics by department.
- Late Arrival Leaderboard: Identify employees with the highest late-arrival minutes.
- Department Trends: Track attendance trends over a date range.
- API Documentation: Explore and test endpoints through Swagger UI.

Technology Stack

- Python
- FastAPI
- MongoDB
- PyMongo
- Pydantic
- Uvicorn

Project Structure


employee-attendance-analytics-api/
├── app/
│   └── main.py
├── sample_data/
│   ├── employees.json
│   └── attendance_logs.json
├── requirements.txt
├── sample_seed.py
├── DATA_MODEL.md
├── DECISIONS.md
├── REVIEW.md
└── openapi.yaml


Prerequisites

- Python 3.11 or later
- MongoDB 6.0 or later

Setup and Run

1. Clone the repository


git clone https://github.com/Varushni17/employee-attendance-analytics-api.git
cd employee-attendance-analytics-api


2. Create and activate a virtual environment

Windows PowerShell:

powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1


3. Install dependencies


python -m pip install -r requirements.txt


4. Configure environment variables

Create a `.env` file in the project root:

dotenv
MONGO_URI=mongodb://localhost:27017
MONGO_DB=attendance_db


Update `MONGO_URI` if your MongoDB instance uses a different connection string. Do not commit `.env` or any credentials to GitHub.

5. Load sample data

Ensure MongoDB is running, then execute:


python sample_seed.py


6. Start the API

bash
python -m uvicorn app.main:app --port 8000 --reload


API Documentation

Once the server is running, open:

- Swagger UI: http://127.0.0.1:8000/docs
- Health Check: http://127.0.0.1:8000/health

Use Swagger UI to explore and test the available API endpoints.

Configuration and Security

- Database connection settings are loaded from environment variables.
- Local environment files and virtual environments are excluded from version control.
- Sample data is provided for local development and testing.

Project Purpose

This project demonstrates backend API development, database integration, employee attendance management, and analytics using Python and MongoDB.
