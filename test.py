# import psycopg2
# from psycopg2 import sql
# from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# # Connection parameters
# host = "proj-db.cn0824m6mgt7.us-east-1.rds.amazonaws.com"
# port = "5432"
# user = "postgres"
# password = "admin1234"
# dbname = "postgres"  # Connect to the default 'postgres' database initially

# try:
#     # Connect to the default 'postgres' database
#     connection = psycopg2.connect(
#         host=host,
#         port=port,
#         user=user,
#         password=password,
#         dbname=dbname
#     )
    
#     connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
#     cursor = connection.cursor()

#     # Check if the database already exists
#     cursor.execute("SELECT 1 FROM pg_database WHERE datname = 'smartassess-db'")
#     exists = cursor.fetchone()

#     if not exists:
#         # Create the new database if it doesn't exist
#         cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier('smartassess-db')))
#         print("Database 'smartassess-db' created successfully.")
#     else:
#         print("Database 'smartassess-db' already exists.")

# except Exception as e:
#     print(f"Error: {e}")

# finally:
#     # Clean up
#     if cursor:
#         cursor.close()
#     if connection:
#         connection.close()

import requests
from pathlib import Path

# Base URL of your FastAPI application
BASE_URL = "http://localhost:8000"

def test_add_university():
    # Step 1: Get authentication token
    login_data = {
        'grant_type': 'password',
        'username': 'abdulsamadsid1@gmail.com',
        'password': '12345',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    login_response = requests.post(
        f"{BASE_URL}/login",
        data=login_data,
        headers=headers
    )
    
    # Extract token
    print("Login Response:", login_response.text)
    token = login_response.json()["access_token"]
    
    
    # Step 2: Prepare headers with token
    headers = {
        "Authorization": f"Bearer {token}"
    }
    
    # Step 3: Prepare university data
    # university_data = {
    #     "university_name": "Test University",
    #     "university_email": "test@university.com",
    #     "phone_number": "1234567890",
    #     "street_address": "123 Test Street",
    #     "city": "Test City",
    #     "state": "Test State",
    #     "zipcode": "12345",
    #     "admin_name": "Test Admin",
    #     "admin_email": "admin1@test.com",
    #     "admin_password": "admin123"
    # }
    
    # # Optional: Prepare image file if needed
    # files = None
    # if Path("university_logo.png").exists():
    #     files = {
    #         "image": ("university_logo.png", open("university_logo.png", "rb"), "image/png")
    #     }
    
    # Step 4: Make request to create university
    response = requests.get(
        f"{BASE_URL}/superadmin/universities",
        # data=university_data,
        headers=headers,
        # files=files
    )
    
    # Step 5: Print response
    print("Status Code:", response.status_code)
    print("Response:", response.text)
    
    # Step 6: Clean up if file was opened
    # if files:
    #     files["image"][1].close()

if __name__ == "__main__":
    test_add_university()