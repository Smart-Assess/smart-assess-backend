import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from io import BytesIO
from apis.universityadmin import (
    add_student,
    get_student,
    delete_student,
    update_student,
    add_teacher,
    get_teacher,
    delete_teacher,
    update_teacher,
)
# Import the model classes needed for the tests
from models.models import Student, Teacher

# Test add_student failures
@pytest.mark.asyncio
async def test_add_student_existing_email(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = True
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await add_student(
            full_name="Test Student",
            department="Computer Science",
            email="existing@student.edu",
            batch="2023",
            section="A",
            password="password123",
            image=None,
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 400
    assert "Student with this email already exists" in exc_info.value.detail

@pytest.mark.asyncio
async def test_add_student_image_upload_failure(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Mock file
    mock_file = MagicMock()
    mock_file.filename = "test.jpg"
    mock_file.read = AsyncMock(return_value=b"test_image_content")
    
    # Mock os functions
    with patch("os.path.join", return_value="temp/test.jpg"), \
         patch("os.makedirs"), \
         patch("builtins.open", mock_open := MagicMock()), \
         patch("os.remove"), \
         patch("apis.universityadmin.upload_to_s3", return_value=None):
        
        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await add_student(
                full_name="Test Student",
                department="Computer Science",
                email="new@student.edu",
                batch="2023",
                section="A",
                password="password123",
                image=mock_file,
                db=mock_db,
                current_admin=mock_current_admin
            )
        
        assert exc_info.value.status_code == 500
        assert "Failed to upload student image" in exc_info.value.detail

# Test get_student failures
@pytest.mark.asyncio
async def test_get_student_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_student(
            student_id="2023-123-CS",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Student not found" in exc_info.value.detail

# Test delete_student failures
@pytest.mark.asyncio
async def test_delete_student_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await delete_student(
            student_id="2023-123-CS",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Student not found" in exc_info.value.detail

# Test update_student failures
@pytest.mark.asyncio
async def test_update_student_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_student(
            student_id="2023-123-CS",
            full_name="Updated Name",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Student not found" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_student_email_taken(monkeypatch):
    # Setup
    mock_student = MagicMock(email="old@student.edu", student_id="2023-123-CS")
    mock_db = MagicMock()
    # First query returns the student, second returns another student with the same email
    mock_db.query.return_value.filter.return_value.first.side_effect = [mock_student, MagicMock()]
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_student(
            student_id="2023-123-CS",
            email="taken@student.edu",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 400
    assert "Email already taken by another student" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_student_image_upload_failure(monkeypatch):
    # Setup
    mock_student = MagicMock(
        email="student@test.edu", 
        student_id="2023-123-CS", 
        image_url="old_image.jpg",
        department="Computer Science",
        batch="2023"
    )
    
    # Create a more targeted mock database
    mock_db = MagicMock()
    
    # First query for finding the student
    mock_db.query.return_value.filter.return_value.first.return_value = mock_student
    
    # For the email validation query, modify the mock behavior
    # We need to specifically mock the second filter call to return a query with no results
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = None  # No duplicate email found
    query_mock.filter.return_value = filter_mock
    
    # Set up the side_effect to handle different query paths
    # First call: get student by ID
    # Second call: Check for email existence (if email is provided)
    mock_db.query.side_effect = [
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_student)))),
        query_mock
    ]
    
    mock_current_admin = MagicMock(university_id=1)
    
    # Mock the delete_from_s3 function to return True
    with patch("apis.universityadmin.delete_from_s3", return_value=True), \
         patch("apis.universityadmin.send_email"), \
         patch("apis.universityadmin.Form", lambda x=None: x), \
         patch("apis.universityadmin.File", lambda x=None: x):
         
        # Mock file
        mock_file = MagicMock()
        mock_file.filename = "test.jpg"
        mock_file.read = AsyncMock(return_value=b"test_image_content")
        
        # Mock functions for image handling
        with patch("builtins.open", MagicMock()), \
            patch("apis.universityadmin.upload_to_s3", side_effect=Exception("S3 upload failed")), \
            patch("os.remove"):
            
            # Execute and Assert
            with pytest.raises(HTTPException) as exc_info:
                await update_student(
                    student_id="2023-123-CS",
                    image=mock_file,
                    email=None,  
                    full_name=None,
                    department=None,
                    batch=None,
                    section=None,
                    password=None,
                    db=mock_db,
                    current_admin=mock_current_admin
                )
            
            assert exc_info.value.status_code == 500
            assert "An error occurred while processing the image" in exc_info.value.detail
  
# Test add_teacher failures
@pytest.mark.asyncio
async def test_add_teacher_existing_email(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = True
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await add_teacher(
            full_name="Test Teacher",
            department="Computer Science",
            email="existing@teacher.edu",
            password="password123",
            image=None,
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 400
    assert "Teacher with this email already exists" in exc_info.value.detail

@pytest.mark.asyncio
async def test_add_teacher_image_upload_failure(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Mock file
    mock_file = MagicMock()
    mock_file.filename = "test.jpg"
    mock_file.read = AsyncMock(return_value=b"test_image_content")
    
    # Mock functions
    with patch("os.path.join", return_value="temp/test.jpg"), \
         patch("os.makedirs"), \
         patch("builtins.open", mock_open := MagicMock()), \
         patch("os.remove"), \
         patch("apis.universityadmin.upload_to_s3", return_value=None):
        
        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await add_teacher(
                full_name="Test Teacher",
                department="Computer Science",
                email="new@teacher.edu",
                password="password123",
                image=mock_file,
                db=mock_db,
                current_admin=mock_current_admin
            )
        
        assert exc_info.value.status_code == 500
        assert "Failed to upload teacher image" in exc_info.value.detail

# Test get_teacher failures
@pytest.mark.asyncio
async def test_get_teacher_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_teacher(
            teacher_id="CS-123",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Teacher not found" in exc_info.value.detail

# Test delete_teacher failures
@pytest.mark.asyncio
async def test_delete_teacher_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await delete_teacher(
            teacher_id="CS-123",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Teacher not found" in exc_info.value.detail

# Test update_teacher failures
@pytest.mark.asyncio
async def test_update_teacher_not_found(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_teacher(
            teacher_id="CS-123",
            full_name="Updated Name",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 404
    assert "Teacher not found" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_teacher_email_taken(monkeypatch):
    # Setup
    mock_teacher = MagicMock(email="old@teacher.edu", teacher_id="CS-123")
    mock_db = MagicMock()
    # First query returns the teacher, second returns another teacher with the same email
    mock_db.query.return_value.filter.return_value.first.side_effect = [mock_teacher, MagicMock()]
    mock_current_admin = MagicMock(university_id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_teacher(
            teacher_id="CS-123",
            email="taken@teacher.edu",
            db=mock_db,
            current_admin=mock_current_admin
        )
    
    assert exc_info.value.status_code == 400
    assert "Email already taken by another teacher" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_teacher_image_upload_failure(monkeypatch):
    # Setup
    mock_teacher = MagicMock(
        email="teacher@test.edu", 
        teacher_id="CS-123", 
        image_url="old_image.jpg",
        department="Computer Science"
    )
    
    # Create a more targeted mock database
    mock_db = MagicMock()
    
    # First query for finding the teacher
    mock_db.query.return_value.filter.return_value.first.return_value = mock_teacher
    
    # For the email validation query, modify the mock behavior
    # We need to specifically mock the second filter call to return a query with no results
    query_mock = MagicMock()
    filter_mock = MagicMock()
    filter_mock.first.return_value = None  # No duplicate email found
    query_mock.filter.return_value = filter_mock
    
    # Set up the side_effect to handle different query paths
    # First call: get teacher by ID
    # Second call: Check for email existence (if email is provided)
    mock_db.query.side_effect = [
        MagicMock(filter=MagicMock(return_value=MagicMock(first=MagicMock(return_value=mock_teacher)))),
        query_mock
    ]
    
    mock_current_admin = MagicMock(university_id=1)
    
    # Mock the delete_from_s3 function to return True
    with patch("apis.universityadmin.delete_from_s3", return_value=True), \
         patch("apis.universityadmin.send_email"), \
         patch("apis.universityadmin.Form", lambda x=None: x), \
         patch("apis.universityadmin.File", lambda x=None: x):
         
        # Mock file
        mock_file = MagicMock()
        mock_file.filename = "test.jpg"
        mock_file.read = AsyncMock(return_value=b"test_image_content")
        
        # Mock functions for image handling
        with patch("builtins.open", MagicMock()), \
            patch("apis.universityadmin.upload_to_s3", side_effect=Exception("S3 upload failed")), \
            patch("os.remove"):
            
            # Execute and Assert
            with pytest.raises(HTTPException) as exc_info:
                await update_teacher(
                    teacher_id="CS-123",
                    image=mock_file,
                    email=None,
                    full_name=None,
                    department=None,
                    password=None,
                    db=mock_db,
                    current_admin=mock_current_admin
                )
            
            assert exc_info.value.status_code == 500
            assert "An error occurred while processing the image" in exc_info.value.detail