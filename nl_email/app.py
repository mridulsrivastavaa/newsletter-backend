import json
import logging
import os
import boto3
import requests
import matplotlib.pyplot as plt
from fpdf import FPDF
from io import BytesIO
from PIL import Image
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.text import MIMEText
from email.utils import formataddr
from boto3.dynamodb.types import TypeDeserializer
from datetime import datetime

# Setup temporary directory (cross-platform)
TMP_DIR = "/tmp" if os.name != "nt" else os.path.join(os.getcwd(), "tmp")
os.makedirs(TMP_DIR, exist_ok=True)

# Initialize logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Initialize services
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("codeforces_data")
user_table = dynamodb.Table("user-table")


def get_user_data(handle):
    logger.info(f"Fetching data from DynamoDB for user: {handle}")
    response = table.query(
        KeyConditionExpression=boto3.dynamodb.conditions.Key('codeforces_id').eq(handle)
    )

    deserializer = TypeDeserializer()
    deserialized_items = []

    for item in response['Items']:
        deserialized_item = {}
        for key, value in item.items():
            if isinstance(value, dict) and 'M' in value:
                deserialized_item[key] = deserializer.deserialize(value)
            else:
                deserialized_item[key] = value
        deserialized_items.append(deserialized_item)

    logger.info(f"Retrieved {len(deserialized_items)} data points for user: {handle}")
    return deserialized_items


def generate_rating_chart(data, handle):
    logger.info(f"Generating rating chart for user: {handle}")
    try:
        dates = [item['date'] for item in data]
        ratings = [int(item['cf_data']['rating']) for item in data]

        plt.figure(figsize=(6, 4))
        plt.plot(dates, ratings, marker='o', color='blue')
        plt.title(f'Rating Trend for {handle}')
        plt.xlabel('Date')
        plt.ylabel('Rating')
        plt.grid(True)

        chart_path = os.path.join(TMP_DIR, f"{handle}_chart.png")
        plt.savefig(chart_path, format='PNG')
        plt.close()
        logger.info(f"Chart generated for {handle} at {chart_path}")
        return chart_path
    except Exception as e:
        logger.error(f"Failed to generate chart for {handle}: {e}")
        raise


def generate_pdf(data, handle):
    logger.info(f"Generating PDF report for user: {handle}")
    try:
        cf_info = data[-1]['cf_data']
        pdf = FPDF()
        pdf.add_page()

        pdf.set_font("Arial", size=14)
        pdf.cell(200, 10, txt=f"Codeforces Report: {handle}", ln=True, align='C')

        avatar_path = os.path.join(TMP_DIR, f"{handle}_avatar.jpg")
        if cf_info.get('avatar'):
            try:
                logger.info(f"Fetching avatar for user: {handle}")
                avatar_img = Image.open(BytesIO(requests.get(cf_info['avatar']).content))
                avatar_img.save(avatar_path)
                pdf.image(avatar_path, x=10, y=20, w=30)
            except Exception as e:
                logger.warning(f"Failed to fetch or insert avatar for {handle}: {e}")

        pdf.set_xy(50, 20)
        pdf.set_font("Arial", size=12)
        pdf.multi_cell(0, 10, txt=f"""
        Name: {cf_info.get('handle', 'N/A')}
        Country: {cf_info.get('country', 'N/A')}
        Organization: {cf_info.get('organization', 'N/A')}
        Rank: {cf_info.get('rank', 'N/A')}
        Rating: {cf_info.get('rating', 'N/A')}
        """)

        chart_path = generate_rating_chart(data, handle)
        pdf.image(chart_path, x=10, y=90, w=180)

        pdf_path = os.path.join(TMP_DIR, f"{handle}_report.pdf")
        pdf.output(pdf_path)
        logger.info(f"PDF generated: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"Error generating PDF for {handle}: {e}")
        raise


def send_email_with_attachment(sender, receiver, subject, body, attachment_path):
    logger.info(f"Sending email to {receiver} with attachment {attachment_path}")
    try:
        ses = boto3.client("ses", region_name="ap-south-1")
        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = formataddr(("Codeforces Reporter", sender))
        msg["To"] = receiver

        msg.attach(MIMEText(body, "plain"))

        with open(attachment_path, "rb") as file:
            part = MIMEApplication(file.read())
            part.add_header("Content-Disposition", "attachment", filename=os.path.basename(attachment_path))
            msg.attach(part)

        response = ses.send_raw_email(
            Source=sender,
            Destinations=[receiver],
            RawMessage={"Data": msg.as_string()}
        )

        logger.info(f"Email sent to {receiver}: Message ID {response['MessageId']}")
        return response
    except Exception as e:
        logger.error(f"Failed to send email to {receiver}: {e}")
        raise


def lambda_handler(event, context):
    sender = "mridul.srivastava03@gmail.com"
    receiver = "mridul.srivastava03@gmail.com"

    try:
        logger.info("Scanning user-table for Codeforces handles.")
        response = user_table.scan()
        users = response.get("Items", [])
        handles = [user['codeforces_id'] for user in users]

        logger.info(f"Found {len(handles)} user(s). Beginning report generation.")

        for handle in handles:
            logger.info(f"Processing user: {handle}")
            user_data = get_user_data(handle)
            pdf_file = generate_pdf(user_data, handle)

            # S3 upload logic
            s3 = boto3.client('s3')
            bucket_name = f"cf-user-{handle.lower()}"  # Ensuring uniqueness and lowercase

            # Check if bucket exists
            try:
                s3.head_bucket(Bucket=bucket_name)
                logger.info(f"S3 bucket '{bucket_name}' already exists.")
            except s3.exceptions.ClientError as e:
                error_code = int(e.response['Error']['Code'])
                if error_code == 404:
                    logger.info(f"Bucket '{bucket_name}' does not exist. Creating new one.")
                    try:
                        s3.create_bucket(
                            Bucket=bucket_name,
                            CreateBucketConfiguration={'LocationConstraint': 'ap-south-1'}
                        )
                        logger.info(f"Bucket '{bucket_name}' created.")
                    except Exception as e:
                        logger.error(f"Failed to create bucket '{bucket_name}': {e}")
                        raise
                else:
                    logger.error(f"Unexpected error checking bucket '{bucket_name}': {e}")
                    raise

            # Upload to S3
            current_date = datetime.now().strftime('%Y-%m-%d')
            s3_key = f"{handle}/{current_date}.pdf"

            try:
                s3.upload_file(pdf_file, bucket_name, s3_key)
                logger.info(f"Uploaded PDF for {handle} to s3://{bucket_name}/{s3_key}")
            except Exception as e:
                logger.error(f"Failed to upload PDF for {handle} to S3: {e}")
                raise

            # Send Email
            latest_info = user_data[-1]['cf_data']
            name = latest_info['handle']
            subject = f"Codeforces Report for {name}"
            body = f"Hi {name},\n\nPlease find attached your latest Codeforces performance report.\n\nBest,\nCodeforces Analytics"
            send_email_with_attachment(sender, receiver, subject, body, pdf_file)

            # Cleanup
            for suffix in ["_report.pdf", "_chart.png", "_avatar.jpg"]:
                file_path = os.path.join(TMP_DIR, f"{handle}{suffix}")
                if os.path.exists(file_path):
                    os.remove(file_path)

            logger.info(f"Cleanup complete for user: {handle}")

    except Exception as e:
        logger.exception("An error occurred during report generation and email process.")
        return {"statusCode": 500, "body": json.dumps({"error": str(e)})}

    logger.info("All emails sent and reports uploaded successfully.")
    return {
        "statusCode": 200,
        "body": json.dumps({"message": "Emails sent and PDFs uploaded to S3."})
    }
