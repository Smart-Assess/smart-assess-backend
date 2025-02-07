
# test_university_admin.py
import requests
from pathlib import Path

BASE_URL = "http://127.0.0.1:8000"

def get_auth_token():
    login_data = {
        'grant_type': 'password',
        'username': 'u@gmail.com',  # University admin email
        'password': '12345',
        'scope': '',
        'client_id': '',
        'client_secret': ''
    }
    
    headers = {
        'accept': 'application/json',
        'Content-Type': 'application/x-www-form-urlencoded'
    }

    try:
        response = requests.post(
            f"{BASE_URL}/login",
            data=login_data,
            headers=headers
        )
        if response.status_code != 200:
            print(f"Login failed: {response.text}")
            return None
        return response.json()["access_token"]
    except Exception as e:
        print(f"Login error: {str(e)}")
        return None

def test_add_teacher():
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    data = {
        "full_name": "Test Teacher",
        "teacher_id": "T123",
        "department": "Computer Science",
        "email": "t@gmail.com",
        "password": "12345"
    }

    # Optional image
    files = None
    image_path = Path("pfp.jpg")
    if image_path.exists():
        files = {
            'image': ('test_image.jpg', open(image_path, 'rb'), 'image/jpeg')
        }

    form_data = {k: (None, v) for k, v in data.items()}
    if files:
        form_data.update(files)

    try:
        response = requests.post(
            f"{BASE_URL}/universityadmin/teacher",
            files=form_data,
            headers={'Authorization': f'Bearer {token}'}
        )
        print(f"Teacher Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error adding teacher: {str(e)}")

def test_update_teacher():
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return

    teacher_id = "324"  # Replace with actual teacher ID
    new_password = "123456"

    data = {

        "password": new_password
    }

    try:
        response = requests.put(
            f"{BASE_URL}/universityadmin/teacher/{teacher_id}",
            data=data,  # Use 'data' for Form fields
            headers={'Authorization': f'Bearer {token}'}
        )
        print(f"Password Update Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error updating teacher password: {str(e)}")

def test_add_student():
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return
    
    data = {
        "full_name": "Test Student",
        "student_id": "S124",
        "department": "Computer Science",
        "email": "s124@gmail.com",
        "batch": "2024",
        "section": "A",
        "password": "12345"
    }

    files = None
    image_path = Path("pfp.jpg")
    if image_path.exists():
        files = {
            'image': ('test_image.jpg', open(image_path, 'rb'), 'image/jpeg')
        }

    form_data = {k: (None, v) for k, v in data.items()}
    if files:
        form_data.update(files)

    try:
        response = requests.post(
            f"{BASE_URL}/universityadmin/student",
            files=form_data,
            headers={'Authorization': f'Bearer {token}'}
        )
        print(f"Student Creation Status: {response.status_code}")
        print(f"Response: {response.json()}")
    except Exception as e:
        print(f"Error adding student: {str(e)}")

def test_update_student():
    """Test updating a student's section."""
    
    token = get_auth_token()
    if not token:
        print("Failed to get authorization token")
        return

    student_id = "S124"  # Replace with an actual student ID
    update_data = {"section": "B"}
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    response = requests.put(
        f"{BASE_URL}/universityadmin/student/{student_id}",
        data=update_data,
        headers=headers
    )

    assert response.status_code == 200, f"Failed to update student. Status Code: {response.status_code}"
    response_json = response.json()
    
    assert response_json.get("student", {}).get("section") == "B", "Section update failed"

    print("Test passed: Student section updated successfully.")
    print(response_json)
if __name__ == "__main__":
    # print("Testing Teacher Creation:")
    # test_add_teacher()
    # print("\nTesting Student Creation:")
    # test_add_student()
    print(test_update_student())