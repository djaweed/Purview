import azure.functions as func
import logging
import json
import os
import traceback
from azure.servicebus import ServiceBusClient, ServiceBusMessage

app = func.FunctionApp()

# Retrieve the container name from an environment variable
STORAGE_CONTAINER_NAME = os.getenv('STORAGE_CONTAINER_NAME')
if not STORAGE_CONTAINER_NAME:
    logging.error("STORAGE_CONTAINER_NAME environment variable is not set.")

# Use the environment variable in the blob trigger path.
@app.blob_trigger(
    arg_name="myblob",
    path=f"{STORAGE_CONTAINER_NAME}/{{name}}",
    connection="WEBSITE_CONTENTAZUREFILECONNECTIONSTRING"
)
def SendtoQueue(myblob: func.InputStream):
    logging.info("SendtoQueue function triggered.")
    logging.info(f"Blob Trigger Details - Name: {myblob.name}, Size: {myblob.length} bytes")
    
    try:
        # Retrieve Service Bus connection string and queue name from environment variables
        servicebus_conn_str = os.getenv('SERVICEBUS_CONNECTION_STRING')
        if not servicebus_conn_str:
            logging.error("SERVICEBUS_CONNECTION_STRING environment variable is not set.")
            return
        
        queue_name = os.getenv('SERVICEBUS_QUEUE_NAME')
        if not queue_name:
            logging.error("SERVICEBUS_QUEUE_NAME environment variable is not set.")
            return

        logging.info("Retrieved Service Bus connection details successfully.")
        
        # Create message data and log the details
        message_data = {
            'blobName': myblob.name
        }
        logging.debug(f"Message data to be sent: {message_data}")
        
        # Convert the message data to a JSON string
        message_json = json.dumps(message_data)
        logging.debug(f"Message JSON: {message_json}")
        
        # Create a ServiceBusMessage
        message = ServiceBusMessage(message_json)
        logging.info("ServiceBusMessage created successfully.")
        
        # Send the message to the Service Bus queue
        with ServiceBusClient.from_connection_string(servicebus_conn_str) as client:
            logging.info("ServiceBusClient created successfully.")
            with client.get_queue_sender(queue_name) as sender:
                logging.info(f"Queue sender acquired for queue: {queue_name}")
                sender.send_messages(message)
                logging.info("Message sent successfully to Service Bus queue.")
        
        logging.info(f"Completed processing for blob: {myblob.name}")
            
    except Exception as e:
        logging.error(f"Error sending to Service Bus: {str(e)}")
        logging.error(traceback.format_exc())
