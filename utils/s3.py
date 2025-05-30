import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import os
from dotenv import load_dotenv

load_dotenv()


def get_s3_client():
    try:
        return boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            region_name=os.getenv("AWS_DEFAULT_REGION"),
        )
    except Exception as e:
        print("AWS credentials not available")


def upload_to_s3(folder_name, file_name, file_path):
    s3_client = get_s3_client()
    print(s3_client)
    print("S3 client created successfully")

    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    s3_key = f"{folder_name}/{file_name}"

    try:
        # Determine if the file is a PDF
        is_pdf = file_name.lower().endswith(".pdf")

        # Set upload parameters based on file type
        if is_pdf:
            s3_client.upload_file(
                file_path,
                bucket_name,
                s3_key,
                ExtraArgs={
                    "ContentType": "application/pdf",
                    "ContentDisposition": "inline",
                },
            )
        else:
            # For non-PDF files, use default behavior
            s3_client.upload_file(file_path, bucket_name, s3_key)

        url = f"https://{bucket_name}.s3.{os.getenv('AWS_DEFAULT_REGION')}.amazonaws.com/{s3_key}"

        return url
    except FileNotFoundError:
        print(f"The file {file_path} was not found")
        return None
    except NoCredentialsError:
        print("AWS credentials not available")
        return None
    except ClientError as e:
        print(f"An error occurred: {e}")
        return None


def delete_from_s3(file_url: str) -> bool:
    """Delete a file from S3 using its URL"""
    s3_client = get_s3_client()

    bucket_name = os.getenv("S3_BUCKET_NAME")
    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    try:
        # Extract key from URL
        # Example URL: https://bucket-name.s3.region.amazonaws.com/folder/file.pdf
        s3_key = file_url.split(".com/")[-1]

        s3_client.delete_object(Bucket=bucket_name, Key=s3_key)
        return True

    except NoCredentialsError:
        print("AWS credentials not available")
        return False
    except ClientError as e:
        print(f"An error occurred: {e}")
        return False


def download_from_s3(s3_url: str, local_path: str, max_retries: int = 3) -> bool:
    """
    Download a file from S3 to a local path with retry logic

    Args:
        s3_url: Full S3 URL of the file
        local_path: Local path to save the file
        max_retries: Maximum number of retry attempts

    Returns:
        bool: True if successful, False otherwise
    """
    s3_client = get_s3_client()
    bucket_name = os.getenv("S3_BUCKET_NAME")

    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    temp_path = f"{local_path}.tmp"
    retry_count = 0

    while retry_count < max_retries:
        try:
            # Extract key from S3 URL
            s3_key = s3_url.split(
                f"{bucket_name}.s3.{os.getenv('AWS_DEFAULT_REGION')}.amazonaws.com/"
            )[1]

            # Download to temporary file first
            s3_client.download_file(Bucket=bucket_name, Key=s3_key, Filename=temp_path)

            # Try to rename temp file to target file
            if os.path.exists(local_path):
                os.remove(local_path)
            os.rename(temp_path, local_path)

            return True

        except PermissionError:
            retry_count += 1
            print(f"File is locked, retrying ({retry_count}/{max_retries})...")
            import time

            time.sleep(1)  # Wait before retry

        except Exception as e:
            print(f"Error downloading from S3: {str(e)}")
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return False

        finally:
            # Cleanup temp file if it exists
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except:
                    pass

    print(f"Failed to download after {max_retries} attempts")
    return False


# def __delete_folder_contents(bucket_name, folder_name):
#     s3_client = get_s3_client()

#     try:
#         response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=folder_name)

#         if 'Contents' not in response:
#             print(f"No files found in the folder {folder_name}")
#             return

#         objects_to_delete = [{'Key': obj['Key']} for obj in response['Contents']]

#         delete_response = s3_client.delete_objects(
#             Bucket=bucket_name,
#             Delete={'Objects': objects_to_delete}
#         )

#         print(f"Deleted {len(objects_to_delete)} objects from {folder_name}")
#     except NoCredentialsError:
#         print("AWS credentials not available")
#     except ClientError as e:
#         print(f"An error occurred: {e}")

# def main():
#     folder_name = "test_folder"
#     file_name = "requirements.txt"
#     file_path = "/home/samaspls/proj/fyp/smart-assess-backend/requirements.txt"

#     download_url = upload_to_s3(folder_name, file_name, file_path)

#     if download_url:
#         print(f"File uploaded successfully. Pre-signed URL (valid for 10 years): {download_url}")
#     else:
#         print("File upload failed.")


if __name__ == "__main__":
    # bucket_name = os.getenv('S3_BUCKET_NAME')
    # if not bucket_name:
    #     raise ValueError("S3_BUCKET_NAME environment variable is not set")
    # main()
    print(
        upload_to_s3(
            "testing",
            "test1.pdf",
            "/home/samadpls/proj/fyp/smart-assess-backend/p3.pdf",
        )
    )

    # delete_from_s3(
    #     "https://smartassess-bucket.s3.eu-north-1.amazonaws.com/university_images/WhatsApp Image 2023-08-24 at 8.20.26 PM.jpeg")
    # Delete all contents in the folders
    # __delete_folder_contents(bucket_name, 'book_images/')
    # __delete_folder_contents(bucket_name, 'maths/')
