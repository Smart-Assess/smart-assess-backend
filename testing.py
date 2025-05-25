import boto3
import os
from datetime import datetime

def get_s3_usage():
    """Get S3 usage using only S3 API calls"""
    
    # Load credentials from .env
    s3_client = boto3.client(
        's3',
        aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
        aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
        region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
    )
    
    bucket_name = os.getenv('S3_BUCKET_NAME', 'smartassessfyp')
    
    try:
        print(f"Checking usage for bucket: {bucket_name}")
        
        # Get all objects in the bucket
        paginator = s3_client.get_paginator('list_objects_v2')
        pages = paginator.paginate(Bucket=bucket_name)
        
        total_size = 0
        total_objects = 0
        file_types = {}
        
        for page in pages:
            if 'Contents' in page:
                for obj in page['Contents']:
                    size = obj['Size']
                    total_size += size
                    total_objects += 1
                    
                    # Track file types
                    key = obj['Key']
                    if '.' in key:
                        ext = key.split('.')[-1].lower()
                        file_types[ext] = file_types.get(ext, {'count': 0, 'size': 0})
                        file_types[ext]['count'] += 1
                        file_types[ext]['size'] += size
                    
                    # Show progress every 100 objects
                    if total_objects % 100 == 0:
                        print(f"Processed {total_objects} objects...")
        
        # Convert bytes to readable format
        def format_bytes(bytes_val):
            for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
                if bytes_val < 1024.0:
                    return f"{bytes_val:.2f} {unit}"
                bytes_val /= 1024.0
            return f"{bytes_val:.2f} PB"
        
        print(f"\n=== S3 Bucket Usage Report ===")
        print(f"Bucket: {bucket_name}")
        print(f"Total Objects: {total_objects:,}")
        print(f"Total Size: {format_bytes(total_size)}")
        print(f"Size in GB: {total_size / (1024**3):.2f} GB")
        print(f"Estimated Monthly Cost: ${(total_size / (1024**3)) * 0.023:.2f}")
        
        print(f"\n=== File Types Breakdown ===")
        for ext, info in sorted(file_types.items(), key=lambda x: x[1]['size'], reverse=True):
            print(f"{ext.upper()}: {info['count']} files, {format_bytes(info['size'])}")
        
        return {
            'bucket_name': bucket_name,
            'total_objects': total_objects,
            'total_size_bytes': total_size,
            'total_size_gb': round(total_size / (1024**3), 2),
            'estimated_monthly_cost': round((total_size / (1024**3)) * 0.023, 2),
            'file_types': file_types
        }
        
    except Exception as e:
        print(f"Error: {e}")
        return None

if __name__ == "__main__":
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    result = get_s3_usage()
    if result:
        print(f"\nSummary: {result['total_objects']} objects using {result['total_size_gb']} GB")
        


# import boto3
# import os
# from datetime import datetime
# from dotenv import load_dotenv

# load_dotenv()

# def list_s3_files(filter_pattern=None, show_details=True):
#     """List files in S3 bucket with optional filtering"""
    
#     s3_client = boto3.client(
#         's3',
#         aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
#         aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
#         region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
#     )
    
#     bucket_name = os.getenv('S3_BUCKET_NAME', 'smartassessfyp')
    
#     try:
#         print(f"Listing files in bucket: {bucket_name}")
#         if filter_pattern:
#             print(f"Filter: {filter_pattern}")
        
#         paginator = s3_client.get_paginator('list_objects_v2')
#         pages = paginator.paginate(Bucket=bucket_name)
        
#         files = []
#         total_size = 0
        
#         for page in pages:
#             if 'Contents' in page:
#                 for obj in page['Contents']:
#                     key = obj['Key']
#                     size = obj['Size']
#                     modified = obj['LastModified']
                    
#                     # Apply filter if specified
#                     if filter_pattern and filter_pattern.lower() not in key.lower():
#                         continue
                    
#                     files.append({
#                         'key': key,
#                         'size': size,
#                         'modified': modified,
#                         'size_mb': round(size / (1024**2), 2)
#                     })
#                     total_size += size
        
#         # Sort by size (largest first)
#         files.sort(key=lambda x: x['size'], reverse=True)
        
#         print(f"\nFound {len(files)} files matching criteria")
#         print(f"Total size: {total_size / (1024**2):.2f} MB ({total_size / (1024**3):.2f} GB)")
        
#         if show_details:
#             print(f"\n{'File Name':<60} {'Size (MB)':<10} {'Modified':<20}")
#             print("-" * 90)
            
#             for file in files:
#                 print(f"{file['key']:<60} {file['size_mb']:<10} {file['modified'].strftime('%Y-%m-%d %H:%M'):<20}")
        
#         return files
        
#     except Exception as e:
#         print(f"Error: {e}")
#         return []

# def delete_s3_files(file_keys, confirm=True):
#     """Delete specified files from S3"""
    
#     if not file_keys:
#         print("No files to delete")
#         return
    
#     if confirm:
#         print(f"\nAbout to delete {len(file_keys)} files:")
#         for key in file_keys[:10]:  # Show first 10
#             print(f"  - {key}")
#         if len(file_keys) > 10:
#             print(f"  ... and {len(file_keys) - 10} more files")
        
#         response = input(f"\nAre you sure you want to delete {len(file_keys)} files? (yes/no): ")
#         if response.lower() != 'yes':
#             print("Deletion cancelled")
#             return
    
#     s3_client = boto3.client(
#         's3',
#         aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
#         aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
#         region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
#     )
    
#     bucket_name = os.getenv('S3_BUCKET_NAME', 'smartassessfyp')
    
#     try:
#         # Delete in batches of 1000 (S3 limit)
#         batch_size = 1000
#         deleted_count = 0
        
#         for i in range(0, len(file_keys), batch_size):
#             batch = file_keys[i:i + batch_size]
            
#             # Prepare delete request
#             delete_request = {
#                 'Objects': [{'Key': key} for key in batch]
#             }
            
#             # Execute deletion
#             response = s3_client.delete_objects(
#                 Bucket=bucket_name,
#                 Delete=delete_request
#             )
            
#             deleted_count += len(response.get('Deleted', []))
            
#             if response.get('Errors'):
#                 for error in response['Errors']:
#                     print(f"Error deleting {error['Key']}: {error['Message']}")
        
#         print(f"Successfully deleted {deleted_count} files")
        
#     except Exception as e:
#         print(f"Error during deletion: {e}")

# def main():
#     print("=== S3 File Manager ===")
#     print("1. List all files")
#     print("2. List report files only")
#     print("3. List PDF files")
#     print("4. List files by custom filter")
#     print("5. Delete report files")
#     print("6. Delete files by custom filter")
    
#     choice = input("\nEnter your choice (1-6): ")
    
#     if choice == "1":
#         files = list_s3_files()
    
#     elif choice == "2":
#         files = list_s3_files(filter_pattern="report")
        
#     elif choice == "3":
#         files = list_s3_files(filter_pattern=".pdf")
        
#     elif choice == "4":
#         pattern = input("Enter filter pattern: ")
#         files = list_s3_files(filter_pattern=pattern)
        
#     elif choice == "5":
#         files = list_s3_files(filter_pattern="report", show_details=False)
#         if files:
#             file_keys = [f['key'] for f in files]
#             delete_s3_files(file_keys)
        
#     elif choice == "6":
#         pattern = input("Enter filter pattern for deletion: ")
#         files = list_s3_files(filter_pattern=pattern, show_details=False)
#         if files:
#             file_keys = [f['key'] for f in files]
#             delete_s3_files(file_keys)
    
#     else:
#         print("Invalid choice")

# if __name__ == "__main__":
#     main()
# import boto3
# import os
# from datetime import datetime, date
# from dotenv import load_dotenv

# load_dotenv()

# def delete_old_assignment_reports():
#     """Delete assignment reports for course 79, assignment 83, but keep the latest from today"""
    
#     s3_client = boto3.client(
#         's3',
#         aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
#         aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
#         region_name=os.getenv('AWS_DEFAULT_REGION', 'us-east-1')
#     )
    
#     bucket_name = os.getenv('S3_BUCKET_NAME', 'smartassessfyp')
    
#     try:
#         # Get all files in the assignment_reports/79/83/ directory
#         prefix = "assignment_reports/79/83/"
        
#         paginator = s3_client.get_paginator('list_objects_v2')
#         pages = paginator.paginate(Bucket=bucket_name, Prefix=prefix)
        
#         files_to_check = []
        
#         for page in pages:
#             if 'Contents' in page:
#                 for obj in page['Contents']:
#                     key = obj['Key']
#                     modified = obj['LastModified']
                    
#                     # Only process PDF report files
#                     if key.endswith('.pdf') and 'report_' in key:
#                         files_to_check.append({
#                             'key': key,
#                             'modified': modified,
#                             'size_mb': round(obj['Size'] / (1024**2), 2)
#                         })
        
#         if not files_to_check:
#             print("No report files found to process")
#             return
        
#         # Sort by modification date (newest first)
#         files_to_check.sort(key=lambda x: x['modified'], reverse=True)
        
#         print(f"Found {len(files_to_check)} report files in assignment_reports/79/83/")
        
#         # Get today's date
#         today = date.today()
        
#         # Find files from today and keep the latest one
#         today_files = []
#         older_files = []
        
#         for file in files_to_check:
#             file_date = file['modified'].date()
#             if file_date == today:
#                 today_files.append(file)
#             else:
#                 older_files.append(file)
        
#         # Files to delete: all older files + all but the latest from today
#         files_to_delete = []
        
#         # Add all older files
#         files_to_delete.extend(older_files)
        
#         # Add all but the latest from today (keep only the most recent one from today)
#         if len(today_files) > 1:
#             files_to_delete.extend(today_files[1:])  # Skip the first (latest) one
        
#         if not files_to_delete:
#             print("No files to delete (keeping the latest from today)")
#             return
        
#         print(f"\nFiles to DELETE ({len(files_to_delete)}):")
#         for file in files_to_delete:
#             print(f"  - {file['key']} ({file['size_mb']} MB) - {file['modified']}")
        
#         if today_files:
#             print(f"\nFiles to KEEP (latest from today):")
#             print(f"  - {today_files[0]['key']} ({today_files[0]['size_mb']} MB) - {today_files[0]['modified']}")
        
#         # Confirm deletion
#         confirm = input(f"\nDelete {len(files_to_delete)} files? (yes/no): ")
#         if confirm.lower() != 'yes':
#             print("Deletion cancelled")
#             return
        
#         # Delete files in batches
#         keys_to_delete = [file['key'] for file in files_to_delete]
        
#         deleted_count = 0
#         batch_size = 1000
        
#         for i in range(0, len(keys_to_delete), batch_size):
#             batch = keys_to_delete[i:i + batch_size]
            
#             delete_request = {
#                 'Objects': [{'Key': key} for key in batch]
#             }
            
#             response = s3_client.delete_objects(
#                 Bucket=bucket_name,
#                 Delete=delete_request
#             )
            
#             deleted_count += len(response.get('Deleted', []))
            
#             if response.get('Errors'):
#                 for error in response['Errors']:
#                     print(f"Error deleting {error['Key']}: {error['Message']}")
        
#         print(f"\nSuccessfully deleted {deleted_count} files")
        
#         # Calculate space saved
#         total_size_mb = sum(file['size_mb'] for file in files_to_delete)
#         print(f"Space saved: {total_size_mb:.2f} MB ({total_size_mb/1024:.2f} GB)")
        
#     except Exception as e:
#         print(f"Error: {e}")

# if __name__ == "__main__":
#     delete_old_assignment_reports()