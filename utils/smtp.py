import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

def send_email(recipient_email, username, password, user_type="admin"):
    smtp_server = "smtp.gmail.com"  # Change this to your SMTP server
    smtp_port = 587  # Change if needed
    sender_email = "smartassess.fyp@gmail.com"  # Change to your email
    sender_password = "jabf cgea ckmf sven"  # Change to your email password
    
    subject_mapping = {
        "admin": "University Registration Successful",
        "student": "Student Registration Successful",
        "teacher": "Teacher Registration Successful"
    }
    
    body_mapping = {
        "admin": f"""
        Dear University Admin,
        
        Your university has been successfully registered.
        
        University Email: {recipient_email}
        Admin Email: {username}
        Admin Password: {password}
        
        Please login and change your password for security reasons.
        
        Best Regards,
        Your Organization Team
        """,
        "student": f"""
        Dear Student,
        
        You have been successfully registered.
        
        Email: {recipient_email}
        Password: {password}
        
        Please login and change your password for security reasons.
        
        Best Regards,
        Your University Team
        """,
        "teacher": f"""
        Dear Teacher,
        
        You have been successfully registered.
        
        Email: {recipient_email}
        Password: {password}
        
        Please login and change your password for security reasons.
        
        Best Regards,
        Your University Team
        """
    }
    
    subject = subject_mapping.get(user_type, "Account Registration Successful")
    body = body_mapping.get(user_type, "")
    
    try:
        # Connect to the SMTP server
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(sender_email, sender_password)
        
        # Prepare email
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = recipient_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        # Send email
        server.sendmail(sender_email, recipient_email, msg.as_string())
        
        server.quit()
        print("Email sent successfully!")
    except Exception as e:
        print(f"Failed to send email: {e}")