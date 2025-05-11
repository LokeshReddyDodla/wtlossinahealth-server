import json
import boto3
from decouple import config


class SQSService:
    def __init__(self, queue_url: str, message_group_id: str = "default"):
        self.queue_url = queue_url
        self.message_group_id = message_group_id
        self.client = boto3.client(
            "sqs",
            region_name=config("AWS_REGION", default="ap-south-1"),
            aws_access_key_id=config("AWS_SQS_ACCESS_KEY_ID"),
            aws_secret_access_key=config("AWS_SQS_SECRET_ACCESS_KEY"),
        )

    def send_message(self, payload: dict, deduplication_id: str):
        response = self.client.send_message(
            QueueUrl=self.queue_url,
            MessageBody=json.dumps(payload),
            MessageGroupId=self.message_group_id,
            MessageDeduplicationId=deduplication_id,
        )
        return response
