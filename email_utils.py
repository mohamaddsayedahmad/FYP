import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Email configuration (replace with your details)
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587
SENDER_EMAIL = 'your_email@gmail.com'  # Your Gmail
SENDER_PASSWORD = 'your_app_password'  # App password, not main password
RECEIVER_EMAIL = 'teacher_email@gmail.com'  # Teacher's email


def send_absence_notification(absent_students, date):
    if not absent_students:
        return "No absences to report."

    # Create email with hourly details
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = RECEIVER_EMAIL
    msg['Subject'] = f"Attendance Alert: Absences on {date}"

    body = f"The following students are marked as absent on {date}:\n\n"
    for student in absent_students:
        body += f"- {student['name']} (Absent at {student['absence_hour']})\n"
    body += "\nPlease follow up as needed."

    msg.attach(MIMEText(body, 'plain'))

    # Send email (unchanged)
    try:
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())
        server.quit()
        return "Email sent successfully."
    except Exception as e:
        return f"Failed to send email: {str(e)}"