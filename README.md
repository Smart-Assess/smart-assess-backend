aSmart Assess Backend
# Smart Assess Backend

## Overview
This project uses FastAPI to build a backend for the Smart Assess application.

## Features
- FastAPI for building APIs
- Asynchronous request handling
- Easy integration with databases
- Automatic interactive API documentation

## Installation
1. Clone the repository:
    ```bash
    git clone git@github.com:Smart-Assess/smart-assess-backend.git
    ```
2. Navigate to the project directory:
    ```bash
    cd smart-assess-backend
    ```
3. Install the dependencies:
    ```bash
    pip install -r requirements.txt
    ```
4. Install `distutils` if not already installed:
    ```bash
    sudo apt-get install python3-distutils
    ```
5. Install `docker-compose` using `pip`:
    ```bash
    pip install docker-compose
    ```

## Usage
To start the FastAPI server, run:
```bash
uvicorn app:app --reload
```

To build and start the server using Docker Compose, run:
```bash
sudo docker compose build
```
if Error than
```bash
sudo docker-compose up
```

To start the server without detached mode, run:
```bash
sudo docker compose up
```
if Error than
```bash
sudo docker-compose up
``` 
