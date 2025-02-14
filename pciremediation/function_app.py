import azure.functions as func
import logging
import hashlib
import os
import json
import re
import traceback
from datetime import datetime
from azure.identity import DefaultAzureCredential
from azure.storage.blob import BlobServiceClient
from azure.data.tables import TableServiceClient
from azure.servicebus import ServiceBusClient, ServiceBusMessage
from azure.core.exceptions import ResourceNotFoundError, ServiceRequestError
from azure.servicebus.exceptions import ServiceBusAuthenticationError
import time

# Get container names at load time
QUARANTINE_CONTAINER = os.getenv('QUARANTINE_CONTAINER')
INPUT_CONTAINER = os.getenv('INPUT_CONTAINER')

logging.info("Starting PCI Remediation Function initialization...")
logging.info(f"Container configuration - Quarantine: {QUARANTINE_CONTAINER}, Input: {INPUT_CONTAINER}")

app = func.FunctionApp()

def retry_with_backoff(func_to_run, max_retries=3, initial_delay=1, exceptions=(ResourceNotFoundError, ServiceRequestError, ServiceBusAuthenticationError)):
    """Retry a function with exponential backoff."""
    for retry in range(max_retries):
        try:
            return func_to_run()
        except exceptions as e:
            if retry == max_retries - 1:  # Last retry
                logging.error(f"Failed after {max_retries} retries: {str(e)}")
                raise
            wait_time = initial_delay * (2 ** retry)  # Exponential backoff
            logging.warning(f"Attempt {retry + 1} failed, retrying in {wait_time} seconds: {str(e)}")
            time.sleep(wait_time)

def verify_servicebus_connection(connection_string: str) -> bool:
    """Verify Service Bus connection string is valid"""
    try:
        # Check if connection string has required parts
        if not all(x in connection_string for x in ['Endpoint=', 'SharedAccessKeyName=', 'SharedAccessKey=']):
            logging.error("Service Bus connection string is missing required components")
            return False
            
        # Try to create a client
        servicebus_client = ServiceBusClient.from_connection_string(connection_string)
        return True
    except Exception as e:
        logging.error(f"Service Bus connection string validation failed: {str(e)}")
        return False

def send_to_queue(servicebus_client, queue_name: str, message_data: dict):
    """Helper function to send messages to Service Bus queues"""
    logging.info(f"Attempting to send message to queue: {queue_name}")
    try:
        def send_servicebus_message():
            with servicebus_client.get_queue_sender(queue_name) as sender:
                # Wrap the payload in a ServiceBusMessage
                message = ServiceBusMessage(json.dumps(message_data))
                try:
                    sender.send_messages(message)
                    logging.info(f"Service Bus message sent successfully to queue: {queue_name}")
                except Exception as e:
                    if "The messaging entity" in str(e) and "could not be found" in str(e):
                        logging.error(f"Queue {queue_name} does not exist")
                    else:
                        logging.error(f"Error sending message: {str(e)}")
                    raise

        retry_with_backoff(
            send_servicebus_message,
            max_retries=3,
            initial_delay=2,
            exceptions=(ServiceBusAuthenticationError, Exception)
        )
    except Exception as e:
        logging.error(f"Failed to send message to {queue_name} after all retries: {str(e)}")
        raise

def process_blob_content(blob_service: BlobServiceClient, container_name: str, blob_name: str) -> (str, str):
    logging.info(f"[STEP 1/4] Starting blob processing for {blob_name} in container {container_name}")
    
    logging.info("Getting container and blob clients...")
    container_client = blob_service.get_container_client(container_name)
    blob_client = container_client.get_blob_client(blob_name)

    logging.info("[STEP 1/4.1] Downloading blob content...")
    try:
        def download_attempt():
            download_stream = blob_client.download_blob()
            return download_stream.readall().decode('utf-8')
            
        original_content = retry_with_backoff(download_attempt)
        logging.info(f"Successfully downloaded {len(original_content)} bytes from blob")
    except Exception as e:
        logging.error(f"Error downloading blob: {str(e)}")
        raise

    logging.info("[STEP 2/4] Starting content redaction...")
    redaction_rules = [
        # Credit card numbers (various formats)
        (r'\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|6(?:011|5[0-9]{2})[0-9]{12})\b', 
         '[REDACTED CREDIT CARD]'),
        # Expiration/Expiry dates in MM/YY or MM/YYYY format
        (r'\b(0[1-9]|1[0-2])/([0-9]{2}|[0-9]{4})\b',
         '[REDACTED EXPIRY]'),
        # Address format
        (r'\d+\s+[A-Za-z\s]+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr)\b', 
         '[REDACTED ADDRESS]')
    ]
    
    # Define a function to hash phone numbers when found
    def hash_phone(match):
        phone = match.group(0)
        hashed = hashlib.sha256(phone.encode('utf-8')).hexdigest()
        return f"[HASHED PHONE: {hashed}]"
    
    # Redaction rule for international phone numbers.
    # This regex is generic and should match a wide variety of international formats.
    redaction_rules.append(
        (r'\+?(?:\d[\s\-.()]?){7,15}\d', hash_phone)
    )

    redacted_content = original_content
    for pattern, replacement in redaction_rules:
        redacted_content = re.sub(pattern, replacement, redacted_content)
    logging.info("Completed initial redaction patterns")

    pci_fields = ['CreditCardNumber', 'CardNumber', 'CCNumber', 'ExpirationDate', 'ExpiryDate', 'Expiry', 'Expiration']
    lines = redacted_content.split('\n')
    if not lines:
        logging.error("Empty content detected")
        raise ValueError("Blob content is empty or not in expected CSV format")
    
    headers = lines[0].split(',')
    logging.info(f"CSV Headers found: {', '.join(headers)}")
    processed_lines = [lines[0]]  # include header

    logging.info("[STEP 3/4] Processing data lines...")
    total_lines = len(lines) - 1  # excluding header
    processed_count = 0

    for line in lines[1:]:
        if not line.strip():
            continue
        values = line.split(',')
        processed_values = [
            '[REDACTED]' if header in pci_fields else value
            for header, value in zip(headers, values)
        ]
        processed_lines.append(','.join(processed_values))
        processed_count += 1
        if processed_count % 1000 == 0:  # Log progress every 1000 lines
            logging.info(f"Processed {processed_count}/{total_lines} lines")

    logging.info(f"Completed processing {processed_count} lines")
    final_content = '\n'.join(processed_lines)
    return original_content, final_content

# The blob trigger is now set to the quarantine container only.
@app.blob_trigger(
    arg_name="myblob",
    path=f"{QUARANTINE_CONTAINER}/{{name}}",
    connection="WEBSITE_CONTENTAZUREFILECONNECTIONSTRING"
)
def pciremediation(myblob: func.InputStream):
    start_time = datetime.utcnow()
    logging.info(f"[FUNCTION START] PCI Remediation triggered at {start_time.isoformat()}")
    logging.info(f"Blob Details:\nName: {myblob.name}\nSize: {myblob.length} bytes")

    try:
        # [STEP 1] Initial Setup
        logging.info("[STEP 1/5] Setting up processing environment...")
        
        # Get blob name from the full path (the placeholder {name} now represents the file name)
        blob_name = myblob.name.split('/')[-1]
        logging.info(f"Processing blob: {blob_name}")
        
        # Get required environment variables
        storage_account = os.getenv('STORAGE_ACCOUNT_NAME')
        success_queue = os.getenv('REDACTION_QUEUE')
        failure_queue = os.getenv('FAILURE_QUEUE')
        table_conn_str = os.getenv('AZURE_STORAGETABLE_CONNECTIONSTRING')
        servicebus_conn_str = os.getenv('AZURE_SERVICEBUS_CONNECTIONSTRING')
        table_name = os.getenv('TABLE_NAME')
        
        # Validate environment variables
        required_vars = {
            'STORAGE_ACCOUNT_NAME': storage_account,
            'AZURE_STORAGETABLE_CONNECTIONSTRING': table_conn_str,
            'AZURE_SERVICEBUS_CONNECTIONSTRING': servicebus_conn_str,
            'QUARANTINE_CONTAINER': QUARANTINE_CONTAINER,
            'INPUT_CONTAINER': INPUT_CONTAINER,
            'TABLE_NAME': table_name,
            'REDACTION_QUEUE': success_queue,
            'FAILURE_QUEUE': failure_queue
        }
        
        for var_name, var_value in required_vars.items():
            if not var_value:
                error_msg = f"{var_name} environment variable is not set"
                logging.error(error_msg)
                raise ValueError(error_msg)
        
        logging.info("All environment variables validated")
        
        # [STEP 2] Initialize Clients
        logging.info("[STEP 2/5] Initializing service clients...")
        logging.info("[STEP 2/5.1] Initializing blob storage client...")
        credential = DefaultAzureCredential()
        account_url = f"https://{storage_account}.blob.core.windows.net"
        blob_service = BlobServiceClient(account_url=account_url, credential=credential)
        
        # Verify Service Bus connection
        logging.info("Verifying Service Bus connection...")
        if not verify_servicebus_connection(servicebus_conn_str):
            raise ValueError("Invalid Service Bus connection string")
            
        logging.info("[STEP 2/5.2] Initializing table and service bus clients...")
        table_client = TableServiceClient.from_connection_string(table_conn_str).get_table_client(table_name)
        servicebus_client = ServiceBusClient.from_connection_string(servicebus_conn_str)
        logging.info("All clients initialized successfully")
        
        # [STEP 3] Process Content
        logging.info("[STEP 3/5] Processing blob content...")
        _, remediated_content = process_blob_content(blob_service, QUARANTINE_CONTAINER, blob_name)
        
        # [STEP 4] Handle Storage Operations
        logging.info("[STEP 4/5] Handling storage operations...")
        quarantine_client = blob_service.get_container_client(QUARANTINE_CONTAINER)
        input_client = blob_service.get_container_client(INPUT_CONTAINER)
        
        # Verify input container exists
        logging.info("[STEP 4/5.1] Verifying input container...")
        try:
            input_client.get_container_properties()
            logging.info(f"Container {INPUT_CONTAINER} exists")
        except Exception:
            logging.info(f"Creating container {INPUT_CONTAINER}...")
            input_client.create_container()
        
        # Upload remediated content with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        name_parts = os.path.splitext(blob_name)
        redacted_blob_name = f"{name_parts[0]}_redacted_{timestamp}{name_parts[1]}"
        logging.info(f"Created redacted filename with timestamp: {redacted_blob_name}")
        
        def upload_attempt():
            input_blob_client = input_client.get_blob_client(redacted_blob_name)
            input_blob_client.upload_blob(remediated_content.encode('utf-8'), overwrite=True)
            
        retry_with_backoff(upload_attempt)
        logging.info(f"Uploaded to {INPUT_CONTAINER}/{redacted_blob_name}")
        
        # Delete original file from the quarantine container
        logging.info("[STEP 4/5.3] Deleting original file...")
        def delete_attempt():
            quarantine_blob_client = quarantine_client.get_blob_client(blob_name)
            quarantine_blob_client.delete_blob()
            
        retry_with_backoff(delete_attempt)
        logging.info(f"Deleted {blob_name} from {QUARANTINE_CONTAINER}")
        
        # [STEP 5] Log to Table Storage and Send Notifications
        logging.info("[STEP 5/5] Creating notifications...")
        
        # Log to table storage
        entity = {
            'PartitionKey': 'pci-finding',
            'RowKey': str(datetime.utcnow().timestamp()),
            'QuarantineContainer': QUARANTINE_CONTAINER,
            'InputContainer': INPUT_CONTAINER,
            'OriginalBlobName': blob_name,
            'RedactedBlobName': redacted_blob_name,
            'ProcessingTime': datetime.utcnow().isoformat()
        }
        table_client.create_entity(entity)
        logging.info("Remediation event logged to Table Storage")
        
        # Send success notification
        success_message = {
            'status': 'success',
            'quarantineContainer': QUARANTINE_CONTAINER,
            'inputContainer': INPUT_CONTAINER,
            'originalBlobName': blob_name,
            'redactedBlobName': redacted_blob_name,
            'processing_time': entity['ProcessingTime']
        }
        send_to_queue(servicebus_client, success_queue, success_message)
        
        end_time = datetime.utcnow()
        duration = (end_time - start_time).total_seconds()
        logging.info(f"[FUNCTION COMPLETE] PCI Remediation completed successfully. Duration: {duration} seconds")
        
    except Exception as e:
        error_msg = f"[ERROR] PCI Remediation failed: {str(e)}"
        logging.error(error_msg, exc_info=True)
        
        # Send failure notification
        try:
            failure_message = {
                'status': 'failed',
                'fileName': blob_name,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat(),
                'stackTrace': traceback.format_exc()
            }
            # Reinitialize servicebus_client for sending the failure message
            servicebus_client = ServiceBusClient.from_connection_string(servicebus_conn_str)
            send_to_queue(servicebus_client, failure_queue, failure_message)
        except Exception as notification_error:
            logging.error(f"Failed to send failure notification: {str(notification_error)}")
        
        raise  # Re-raise the original exception
