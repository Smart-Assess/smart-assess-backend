import boto3
from botocore.exceptions import NoCredentialsError, ClientError
import os
from dotenv import load_dotenv

load_dotenv()


def get_s3_client():
    return boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION')
    )


def upload_to_s3(folder_name, file_name, file_path):
    s3_client = get_s3_client()

    bucket_name = os.getenv('S3_BUCKET_NAME')
    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    s3_key = f"{folder_name}/{file_name}"

    try:
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

    bucket_name = os.getenv('S3_BUCKET_NAME')
    if not bucket_name:
        raise ValueError("S3_BUCKET_NAME environment variable is not set")

    try:
        # Extract key from URL
        # Example URL: https://bucket-name.s3.region.amazonaws.com/folder/file.pdf
        s3_key = file_url.split('.com/')[-1]

        s3_client.delete_object(
            Bucket=bucket_name,
            Key=s3_key
        )
        return True

    except NoCredentialsError:
        print("AWS credentials not available")
        return False
    except ClientError as e:
        print(f"An error occurred: {e}")
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

    delete_from_s3(
        "https://smartassess-bucket.s3.eu-north-1.amazonaws.com/university_images/WhatsApp Image 2023-08-24 at 8.20.26 PM.jpeg")
    # Delete all contents in the folders
    # __delete_folder_contents(bucket_name, 'book_images/')
    # __delete_folder_contents(bucket_name, 'maths/')
