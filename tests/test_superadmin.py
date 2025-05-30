import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi import HTTPException
from io import BytesIO
from apis.superadmin import (
    add_university,
    get_university,
    delete_university,
    update_university,
)

# Test add_university failures


@pytest.mark.asyncio
async def test_add_university_existing_university_email(monkeypatch):
    # Setup
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = True
    mock_current_admin = MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await add_university(
            university_name="Test University",
            university_email="existing@university.edu",
            phone_number="123456789",
            street_address="123 Test Street",
            city="Test City",
            state="Test State",
            zipcode="12345",
            admin_name="Admin Name",
            admin_email="admin@university.edu",
            admin_password="password123",
            image=None,  # Add the missing image parameter
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 400
    assert "University with this email already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_add_university_existing_admin_email(mocker):
    # Setup
    mock_db = mocker.MagicMock()
    # First query returns None (university doesn't exist)
    mock_db.query.return_value.filter.return_value.first.side_effect = [None, True]
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await add_university(
            university_name="Test University",
            university_email="new@university.edu",
            phone_number="123456789",
            street_address="123 Test Street",
            city="Test City",
            state="Test State",
            zipcode="12345",
            admin_name="Admin Name",
            admin_email="existing@admin.edu",
            admin_password="password123",
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 400
    assert "University admin with this email already exists" in exc_info.value.detail


@pytest.mark.asyncio
async def test_add_university_image_upload_failure(mocker):
    # Setup
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = mocker.MagicMock(id=1)

    # Mock file
    mock_file = MagicMock()
    mock_file.filename = "test.jpg"
    mock_file.read = AsyncMock(return_value=b"test_image_content")

    # Mock os functions
    mocker.patch("os.path.join", return_value="temp/test.jpg")
    mocker.patch("os.makedirs")
    mock_open = mocker.patch("builtins.open", mocker.mock_open())
    mocker.patch("os.remove")

    # Mock S3 upload to fail
    mocker.patch("apis.superadmin.upload_to_s3", return_value=None)

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await add_university(
            university_name="Test University",
            university_email="new@university.edu",
            phone_number="123456789",
            street_address="123 Test Street",
            city="Test City",
            state="Test State",
            zipcode="12345",
            admin_name="Admin Name",
            admin_email="admin@university.edu",
            admin_password="password123",
            image=mock_file,
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 500
    assert "Failed to upload university image" in exc_info.value.detail


# Test get_university failures


@pytest.mark.asyncio
async def test_get_university_not_found(mocker):
    # Setup
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_university(
            university_id=999, db=mock_db, current_admin=mock_current_admin
        )

    assert exc_info.value.status_code == 404
    assert "University not found or access denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_get_university_admin_not_found(mocker):
    # Setup
    mock_university = mocker.MagicMock()
    mock_db = mocker.MagicMock()
    # University exists but admin doesn't
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_university,
        None,
    ]
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await get_university(
            university_id=1, db=mock_db, current_admin=mock_current_admin
        )

    assert exc_info.value.status_code == 404
    assert "University admin not found" in exc_info.value.detail


# Test delete_university failures


@pytest.mark.asyncio
async def test_delete_university_not_found(mocker):
    # Setup
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await delete_university(
            university_id=999, db=mock_db, current_admin=mock_current_admin
        )

    assert exc_info.value.status_code == 404
    assert "University not found or access denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_delete_university_db_error(mocker):
    # Setup
    mock_university = mocker.MagicMock()
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_university
    mock_db.query.return_value.filter.return_value.count.return_value = 1
    mock_db.delete.side_effect = Exception("Database error")
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await delete_university(
            university_id=1, db=mock_db, current_admin=mock_current_admin
        )

    assert exc_info.value.status_code == 500
    assert "Failed to delete university" in exc_info.value.detail
    mock_db.rollback.assert_called_once()


# Test update_university failures


@pytest.mark.asyncio
async def test_update_university_not_found(mocker):
    # Setup
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_university(
            university_id=999,
            university_name="Updated University",
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 404
    assert "University not found or access denied" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_university_email_taken(mocker):
    # Setup
    mock_university = mocker.MagicMock(email="old@university.edu", id=1)
    mock_existing_university = mocker.MagicMock()
    mock_db = mocker.MagicMock()
    # First query returns the university, second returns another university with the same email
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_university,
        mock_existing_university,
        None,
    ]
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_university(
            university_id=1,
            university_email="taken@university.edu",
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 400
    assert "Email already taken by another university" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_university_admin_not_found(mocker):
    # Setup
    mock_university = mocker.MagicMock(email="old@university.edu", id=1)
    mock_db = mocker.MagicMock()
    # University exists but admin doesn't
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_university,
        None,
        None,
    ]
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_university(
            university_id=1,
            university_name="Updated University",
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 404
    assert "University admin not found" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_university_admin_email_taken(mocker):
    # Setup
    mock_university = mocker.MagicMock(email="uni@test.edu", id=1)
    mock_university_admin = mocker.MagicMock(email="old@admin.edu", id=1)
    mock_existing_admin = mocker.MagicMock()
    mock_db = mocker.MagicMock()
    # First query returns the university, second returns the admin, third returns another admin with the same email
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_university,
        None,
        mock_university_admin,
        mock_existing_admin,
    ]
    mock_current_admin = mocker.MagicMock()

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_university(
            university_id=1,
            admin_email="taken@admin.edu",
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 400
    assert "Email already taken by another admin" in exc_info.value.detail


@pytest.mark.asyncio
async def test_update_university_image_upload_failure(mocker):
    # Setup
    mock_university = mocker.MagicMock(email="uni@test.edu", id=1, image_url=None)
    mock_university_admin = mocker.MagicMock(email="admin@test.edu", id=1)
    mock_db = mocker.MagicMock()
    mock_db.query.return_value.filter.return_value.first.side_effect = [
        mock_university,
        None,
        mock_university_admin,
        None,
    ]
    mock_current_admin = mocker.MagicMock()

    # Mock file
    mock_file = MagicMock()
    mock_file.filename = "test.jpg"
    mock_file.read = AsyncMock(return_value=b"test_image_content")

    # Mock file operations
    # Match the path in the implementation
    mocker.patch("os.path.join", return_value="/tmp/test.jpg")
    mocker.patch("builtins.open", mocker.mock_open())

    # Mock S3 upload to raise an exception instead of returning None
    mocker.patch(
        "apis.superadmin.upload_to_s3", side_effect=Exception("S3 upload failed")
    )
    mocker.patch("os.remove")  # Mock the cleanup

    # Execute and Assert
    with pytest.raises(HTTPException) as exc_info:
        await update_university(
            university_id=1,
            university_name="Updated University",
            image=mock_file,
            db=mock_db,
            current_admin=mock_current_admin,
        )

    assert exc_info.value.status_code == 500
    assert "An error occurred while processing the image" in exc_info.value.detail
