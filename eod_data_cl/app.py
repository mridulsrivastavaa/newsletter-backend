import json
import boto3
import requests
import logging
from datetime import datetime
import pytz

# Set up logging
logger = logging.getLogger()
logger.setLevel(logging.INFO)

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("codeforces_data")

def lambda_handler(event, context):
    try:
        logger.info("Step 1: Scanning DynamoDB table for Codeforces handles.")
        response = table.scan()
        users = response.get("Items", [])
        handles = [user['codeforces_id'] for user in users if 'codeforces_id' in user]

        logger.info(f"Found {len(handles)} Codeforces handles.")

        if not handles:
            logger.warning("No valid Codeforces handles found.")
            return {
                "statusCode": 400,
                "body": json.dumps({"message": "No valid Codeforces handles found in DynamoDB"})
            }

        logger.info("Step 2: Fetching user data from Codeforces API.")
        cf_api = "https://codeforces.com/api/user.info?handles=" + ";".join(handles)
        cf_response = requests.get(cf_api)
        data = cf_response.json()

        if data.get("status") != "OK":
            logger.error("Codeforces API returned an error.")
            return {
                "statusCode": 502,
                "body": json.dumps({"message": "Failed to fetch data from Codeforces API"})
            }

        ist = pytz.timezone('Asia/Kolkata')
        today_str = datetime.now(ist).strftime('%Y-%m-%d')
        logger.info(f"Current IST date: {today_str}")

        # Step 3: Updating DynamoDB
        codeforces_users = data["result"]
        failed_users = []

        logger.info("Step 3: Writing user data to DynamoDB.")
        for user_data in codeforces_users:
            try:
                handle = user_data['handle']
                table.put_item(
                    Item={
                        'codeforces_id': handle,
                        'date': today_str,
                        'cf_data': user_data
                    }
                )
                logger.info(f"Successfully saved data for user: {handle}")
            except Exception as item_error:
                logger.error(f"Failed to save data for {handle}: {item_error}")
                failed_users.append(handle)

        if failed_users:
            logger.warning(f"Partial success. Failed users: {failed_users}")
            return {
                "statusCode": 207,
                "body": json.dumps({
                    "message": "Partial success",
                    "failed_users": failed_users
                })
            }

        logger.info("All user data successfully saved.")
        return {
            "statusCode": 200,
            "body": json.dumps({"message": "Successfully updated Codeforces data"})
        }

    except Exception as e:
        logger.exception("Unhandled exception occurred during Lambda execution.")
        return {
            "statusCode": 500,
            "body": json.dumps({"message": "Internal server error", "error": str(e)})
        }
