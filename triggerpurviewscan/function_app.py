#Working Copy
import azure.functions as func
import logging
import json
import os
import uuid
import requests
from azure.identity import DefaultAzureCredential, ClientSecretCredential
import traceback

logging.basicConfig(level=logging.INFO)

SCAN_API_VERSION = "2018-12-01-preview"  # Using consistent API version from blog

app = func.FunctionApp()

def get_purview_token():
    """Get a token for Purview with the correct scopes."""
    logging.info("Attempting to acquire Purview token...")
    
    client_id = os.getenv("AZURE_CLIENT_ID")
    client_secret = os.getenv("AZURE_CLIENT_SECRET")
    tenant_id = os.getenv("AZURE_TENANT_ID")
    
    try:
        if not all([client_id, client_secret, tenant_id]):
            raise ValueError("Missing required environment variables for authentication")
            
        credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret
        )
        
        scope = "https://purview.azure.net/.default"
        token = credential.get_token(scope)
        
        if not token:
            raise Exception("Failed to get token")
            
        logging.info(f"Successfully acquired token")
        return token.token
        
    except Exception as e:
        logging.error(f"Failed to acquire token: {str(e)}")
        logging.error(f"Token acquisition error details: {traceback.format_exc()}")
        raise

def create_scan_filter(purview_account: str, datasource_name: str, scan_name: str, token: str, storage_name: str, container_name: str):
    """Create a filter for the scan following the blog's approach."""
    try:
        filter_url = f"https://{purview_account}.purview.azure.com/scan/datasources/{datasource_name}/scans/{scan_name}/filters/custom"
        full_filter_url = f"{filter_url}?api-version={SCAN_API_VERSION}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Following the blog's format for filter
        filter_body = {
            "properties": {
                "includeUriPrefixes": [
                    f"https://{storage_name}.dfs.core.windows.net/{container_name}"
                ],
                "excludeUriPrefixes": []
            }
        }

        logging.info(f"Creating scan filter with URL: {full_filter_url}")
        logging.info(f"Filter body: {json.dumps(filter_body, indent=2)}")

        response = requests.put(
            full_filter_url,
            headers=headers,
            json=filter_body
        )

        logging.info(f"Filter Creation Response: {response.status_code}")
        logging.info(f"Filter Response Body: {response.text}")

        if response.status_code not in [200, 201, 202]:
            raise Exception(f"Failed to create filter. Status: {response.status_code}, Response: {response.text}")

        return response.json()

    except Exception as e:
        logging.error(f"Error creating scan filter: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise

def run_purview_scan(purview_account: str, datasource_name: str, scan_name: str, token: str):
    """Run a Purview scan with the specified parameters."""
    try:
        run_id = str(uuid.uuid4())
        
        # Using preview API version for running the scan
        base_url = f"https://{purview_account}.purview.azure.com/scan/datasources/{datasource_name}/scans/{scan_name}/runs/{run_id}"
        full_url = f"{base_url}?api-version={SCAN_API_VERSION}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Simplified run body based on blog example
        run_body = {
            "scanLevel": "Full"
        }
        
        logging.info(f"Making scan run request to: {full_url}")
        
        response = requests.put(
            full_url,
            headers=headers,
            json=run_body
        )
        
        logging.info(f"Scan Run Response: Status {response.status_code}, Body: {response.text}")
        
        if response.status_code not in [200, 201, 202]:
            raise Exception(f"Failed to run scan. Status: {response.status_code}, Response: {response.text}")
            
        return run_id

    except Exception as e:
        logging.error(f"Error running scan: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise

@app.service_bus_queue_trigger(
    arg_name="azservicebus", 
    queue_name="dlp-alerts",
    connection="SERVICEBUS_CONNECTION_STRING"
) 
def TriggerPurviewScan(azservicebus: func.ServiceBusMessage):
    try:
        logging.info("Starting servicebus_trigger1 function")
        
        # Get environment variables
        purview_account = os.getenv("PURVIEW_ACCOUNT")
        datasource_name = os.getenv("PURVIEW_DATASOURCE_NAME")
        collection_name = os.getenv("PURVIEW_COLLECTION_NAME")
        storage_name = os.getenv("STORAGE_ACCOUNT_NAME")
        target_container = "input-dlp-files"

        # Using fixed scan name based on container
        scan_name = f"dlp-container-scan"  # Fixed name for the scan

        logging.info("Environment Configuration:")
        logging.info(f"Purview Account: {purview_account}")
        logging.info(f"Data Source Name: {datasource_name}")
        logging.info(f"Collection Name: {collection_name}")
        logging.info(f"Storage Account: {storage_name}")
        logging.info(f"Target Container: {target_container}")
        logging.info(f"Scan Name: {scan_name}")

        if not all([purview_account, datasource_name, collection_name, storage_name]):
            missing_vars = [var for var, value in {
                "PURVIEW_ACCOUNT": purview_account,
                "PURVIEW_DATASOURCE_NAME": datasource_name,
                "PURVIEW_COLLECTION_NAME": collection_name,
                "STORAGE_ACCOUNT_NAME": storage_name
            }.items() if not value]
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

        token = get_purview_token()
        
        # First, create/update the scan
        url = f"https://{purview_account}.purview.azure.com/scan/datasources/{datasource_name}/scans/{scan_name}"
        full_url = f"{url}?api-version={SCAN_API_VERSION}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        # Basic scan configuration
        body_input = {
            "kind": "AdlsGen2Msi",
            "properties": {
                "scanLevel": "Full",
                "scanRulesetName": "AdlsGen2",
                "scanRulesetType": "System",
                "collection": {
                    "referenceName": collection_name,
                    "type": "CollectionReference"
                }
            }
        }

        logging.info("Creating/Updating scan:")
        logging.info(f"URL: {full_url}")
        logging.info(f"Request Body: {json.dumps(body_input, indent=2)}")

        response = requests.put(
            full_url,
            headers=headers,
            json=body_input
        )

        logging.info(f"Scan Creation/Update Response:")
        logging.info(f"Status Code: {response.status_code}")
        logging.info(f"Response Body: {response.text}")

        if response.status_code in [200, 201, 202]:
            logging.info(f"Successfully created/updated scan: {scan_name}")
            
            # Create/Update the filter
            filter_response = create_scan_filter(
                purview_account=purview_account,
                datasource_name=datasource_name,
                scan_name=scan_name,
                token=token,
                storage_name=storage_name,
                container_name=target_container
            )
            logging.info("Successfully created/updated filter")
            
            # Run the scan
            run_id = run_purview_scan(
                purview_account=purview_account,
                datasource_name=datasource_name,
                scan_name=scan_name,
                token=token
            )
            logging.info(f"Initiated scan run with ID: {run_id}")
            
        else:
            error_msg = f"Failed to create/update scan. Status: {response.status_code}, Response: {response.text}"
            logging.error(error_msg)
            raise Exception(error_msg)

    except Exception as e:
        logging.error(f"Unexpected Error: {str(e)}")
        logging.error(f"Full traceback: {traceback.format_exc()}")
        raise

    finally:
        logging.info("Completed servicebus_trigger1 function execution")
