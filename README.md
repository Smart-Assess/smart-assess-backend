
![Screenshot from 2025-05-30 21-41-40](https://github.com/user-attachments/assets/d2a43fd3-e90f-4f34-a583-b11b5b04fa57) 


![Supported python versions](https://img.shields.io/badge/python-3.7%20%7C%203.8%20%7C%203.9%20%7C%203.10%20%7C%203.11-blue)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![License](https://img.shields.io/badge/License-MIT%202.0-blue.svg)](LICENSE)
[![Run Pytest](https://github.com/samadpls/BestRAG/actions/workflows/pytest.yml/badge.svg?branch=main)](https://github.com/samadpls/BestRAG/actions/workflows/pytest.yml)

## 🌟 Overview

In the current educational landscape, the grading process for academic assignments is often time-consuming, subjective, and inconsistent. This leads to challenges in providing timely and personalized feedback to students. Teachers face difficulties managing large volumes of submissions, which can result in delayed grading and inadequate insights into student performance. This delay not only hampers students' ability to understand their mistakes and improve but also affects their overall learning experience and motivation.

Smart Assess develops an advanced web-based grading platform using Natural Language Processing (NLP) to automate assignment evaluations. It provides detailed, context-aware grading and feedback, reduces grading time, and includes features like grammar checking, AI detection, and plagiarism detection. This enhances the grading experience for teachers and offers students timely feedback for academic growth. 🎓

## ✨ Features
-   🚀 FastAPI for building APIs
-   🔄 Asynchronous request handling
-   💾 Easy integration with databases
-   📖 Automatic interactive API documentation
-   🤖 AI-powered text evaluation
-   ✍️ Grammar checking
-   🔎 Plagiarism detection

## 🛠️ Local Development Setup

### Prerequisites
-   🐍 Python 3.8+
-   🐳 Docker and Docker Compose
-   🐙 Git

### Installation
1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Smart-Assess/smart-assess-backend.git
    ```
2.  **Navigate to the project directory:**
    ```bash
    cd smart-assess-backend
    ```
3.  **Create your environment configuration file:**
    Copy the example environment file (`.env.example`) to `.env`:
    ```bash
    cp .env.example .env 
    ```
    Then, populate `.env` with your local configuration details (e.g., database credentials, API keys for any services you might use locally). You will need to acquire your own API keys for services like Qdrant if you intend to use them.

4.  **Install Python dependencies** (optional if primarily using Docker, but good for local tooling/testing):
    ```bash
    pip install -r requirements.txt
    ```

## 🚀 Running the Application

### Using Docker (Recommended for local development) 🐳

1.  **Build and run the services:**
    From the project root directory (`smart-assess-backend`), run:
    ```bash
    docker compose up --build
    ```
    To run in detached mode (in the background):
    ```bash
    docker compose up -d --build
    ```

2.  **Access the application:**
    The API will typically be available at `http://localhost:8000` (or the port configured in your Docker setup). The interactive API documentation (Swagger UI) will be at `http://localhost:8000/docs`.

3.  **Common Docker Compose commands:**
    *   📜 Check logs: `docker compose logs -f`
    *   🔄 Restart services: `docker compose restart`
    *   🛑 Stop services: `docker compose down`
    *   🏗️ To rebuild images and restart: `docker compose up -d --build`

### Using Uvicorn (Directly, without Docker) ⚙️

1.  Ensure all dependencies from `requirements.txt` are installed in your local Python environment.
2.  Make sure your `.env` file is correctly configured.
3.  Start the FastAPI server:
    ```bash
    uvicorn app.main:app --reload
    ```
    The `--reload` flag enables auto-reloading when code changes are detected.

## 👥 Team Members

This project was made possible by the hard work and dedication of the following team members:

-   Abdul Samad Siddiqui ([@samadpls](https://github.com/samadpls)) - Lead
-   Maira Usman ([@Myrausman](https://github.com/Myrausman))
-   Ahsan Sajid ([@AhsanSajid](https://github.com/AhsanSajid))
-   Rayyan ([@Rayyan](https://github.com/Rayyan))

Thank you to the entire team for their contributions! 🎉