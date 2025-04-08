import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
import json
import os
import inspect
from functools import wraps
from apis.teacher_course import (
    create_course,
    get_course,
    regenerate_course_code,
    get_teacher_courses,
    update_course,
    delete_course,
    update_course_request,
    get_course_requests
)
from models.models import Course, StudentCourse, Student

def mock_fastapi_deps(func):
    """Decorator to replace FastAPI Form, File, etc. with simple values in tests"""
    original_sig = inspect.signature(func)
    
    @wraps(func)
    async def wrapper(*args, **kwargs):
        # Convert any Form() or File() parameters to their underlying values
        for param_name, param in original_sig.parameters.items():
            if param_name in kwargs and param.default is not param.empty:
                if hasattr(param.default, '__class__') and param.default.__class__.__name__ in ['Form', 'File']:
                    # Replace with the inner value of the Form or File object
                    if param.default.default is not ...:  # ... is Ellipsis, used for required fields
                        kwargs[param_name] = param.default.default
        
        return await func(*args, **kwargs)
    
    return wrapper

# Apply the decorator to our target functions
patched_update_course = mock_fastapi_deps(update_course)

# Test create_course failures
@pytest.mark.asyncio
async def test_create_course_invalid_file_format():
    # Setup
    mock_db = MagicMock()
    mock_current_teacher = MagicMock(id=1)
    
    # Create mock file with invalid extension
    mock_file = MagicMock()
    mock_file.filename = "test.txt"
    mock_file.read = AsyncMock(return_value=b"test content")
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await create_course(
            name="Test Course",
            batch="2023",
            group="A",
            section="Morning",
            status="active",
            files=[mock_file],
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 400
    assert "must be a PDF or PPT" in exc_info.value.detail


# Test get_course failures
@pytest.mark.asyncio
async def test_get_course_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_course(
            course_id=999,
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail

# Test regenerate_course_code failures
@pytest.mark.asyncio
async def test_regenerate_course_code_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await regenerate_course_code(
            course_id=999,
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail

# Test update_course failures
@pytest.mark.asyncio
async def test_update_course_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_course(
            course_id=999,
            name="Updated Course",
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_course_s3_upload_failure():
    # Setup
    mock_course = MagicMock(
        id=1,
        teacher_id=1,
        pdf_urls=json.dumps([]),
        collection_name="test_collection"
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_course
    mock_current_teacher = MagicMock(id=1)
    
    # Create mock file with valid content type
    mock_file = MagicMock()
    mock_file.filename = "test.pdf"
    mock_file.content_type = "application/pdf"
    mock_file.read = AsyncMock(return_value=b"test pdf content")
    
    # Mock Form and File classes
    with patch("apis.teacher_course.Form", lambda x=None: x), \
         patch("apis.teacher_course.File", lambda x=None: x):
        
        # Mock file and S3 operations
        with patch("tempfile.NamedTemporaryFile", return_value=MagicMock(name="temp.pdf")), \
             patch("apis.teacher_course.get_teacher_rag", return_value=MagicMock()), \
             patch("os.path.exists", return_value=True), \
             patch("os.remove"), \
             patch("apis.teacher_course.upload_to_s3", return_value=None):  # Simulate S3 upload failure
            
            # Execute and Assert
            with pytest.raises(HTTPException) as exc_info:
                await update_course(
                    course_id=1,
                    pdfs=[mock_file],
                    name=None,
                    batch=None,
                    group=None,
                    section=None,
                    status=None,
                    removed_pdfs=None,
                    db=mock_db,
                    current_teacher=mock_current_teacher
                )
            
            assert exc_info.value.status_code == 500
            assert "Failed to upload PDF" in exc_info.value.detail


# Test delete_course failures
@pytest.mark.asyncio
async def test_delete_course_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await delete_course(
            course_id=999,
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail

@pytest.mark.asyncio
async def test_delete_course_db_error():
    # Setup
    mock_course = MagicMock(
        id=1,
        teacher_id=1,
        pdf_urls=json.dumps(["https://example.com/test.pdf"]),
        collection_name="test_collection"
    )
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_course
    mock_db.delete.side_effect = Exception("Database error")  # Simulate DB error
    mock_current_teacher = MagicMock(id=1)
    
    # Mock RAG and S3 operations
    with patch("apis.teacher_course.delete_from_s3", return_value=True), \
         patch("apis.teacher_course.get_teacher_rag", return_value=MagicMock()):
        
        # Execute and Assert
        with pytest.raises(HTTPException) as exc_info:
            await delete_course(
                course_id=1,
                db=mock_db,
                current_teacher=mock_current_teacher
            )
        
        assert exc_info.value.status_code == 500
        assert "Error deleting course" in exc_info.value.detail

# Test update_course_request failures
@pytest.mark.asyncio
async def test_update_course_request_invalid_status():
    # Setup
    mock_db = MagicMock()
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_course_request(
            course_id=1,
            request_id=1,
            status="invalid",  # Invalid status
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 400
    assert "Status must be 'accepted' or 'rejected'" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_course_request_course_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_course_request(
            course_id=999,
            request_id=1,
            status="accepted",
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail

@pytest.mark.asyncio
async def test_update_course_request_request_not_found():
    # Setup
    mock_course = MagicMock(id=1, teacher_id=1)
    mock_db = MagicMock()
    # Course found but request not found
    mock_db.query.return_value.filter.return_value.first.side_effect = [mock_course, None]
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_course_request(
            course_id=1,
            request_id=999,
            status="accepted",
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Request not found" in exc_info.value.detail

# Test get_course_requests failures
@pytest.mark.asyncio
async def test_get_course_requests_course_not_found():
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None  # Course not found
    mock_current_teacher = MagicMock(id=1)
    
    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_course_requests(
            course_id=999,
            db=mock_db,
            current_teacher=mock_current_teacher
        )
    
    assert exc_info.value.status_code == 404
    assert "Course not found" in exc_info.value.detail