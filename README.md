**# Purview: Automated Azure Purview Scanning & Remediation

## Overview
This project implements an automated data classification and redaction workflow based on **PCI (Payment Card Industry) standards**. When a file is uploaded to an Azure Blob Storage container, a series of Azure services are triggered to classify, quarantine, and redact the data, while routing metadata and notifications accordingly. This can be used as part of a downstream application or as a standalone solution. The repository also includes a Python function to generate fake customer data for experimentation.

## Workflow Overview
1. **File Upload**  
   A file is uploaded to the primary Azure Blob Storage container.
2. **Blob Trigger**  
   The upload triggers an Azure Function which sends file details to an Azure Service Bus queue.
3. **Service Bus Processing**  
   A second Azure Function, listening on the Service Bus, processes the message and triggers an Azure Purview scan for PCI classification.
4. **Purview Alert**  
   If sensitive PCI data is detected, Purview raises an alert via a Log Analytics custom query that triggers a Logic App.
5. **Quarantine Process**  
   The Logic App copies the file from the original blob storage to a quarantine blob storage.
6. **Data Redaction**  
   An Azure Function then redacts the sensitive data in the file. This function also updates a metadata table and sends a message to another Service Bus.
7. **Queue Routing & Notifications**  
   - **Success:** Routed to a "success" queue if redaction succeeds.  
   - **Failure:** Routed to a "failure" queue and sends an email via Azure Communication Service.

## Important Things to Note
- At the data catalog level, you must explicitly grant permissions—these aren't inherited from the resource group or Purview application level.
- If you use Python v2 for Azure Functions, decorators handle function bindings and you don't need a `function.json`. For Python v1, you must manually define bindings in `function.json`.
- This was deployed with a CI/CD pipeline—edit the GitHub Actions workflows (`.yml` files) once you connect your repo to your Function Apps.
- Ensure all necessary environment variables are set in **Application Settings** (connection strings, account names, etc.).

## Learning Improvements
- Microsoft’s Purview documentation can lag behind new API versions. We reverse-engineered some calls via browser DevTools.
- Python Functions v2 simplifies binding management with decorators.

## Prerequisites
- **Python 3.11**  
- Azure subscription with:
  - Azure Blob Storage (initial & quarantine containers)  
  - Azure Service Bus  
  - Azure Purview  
  - Azure Logic Apps  
  - Azure Communication Service  
  - Azure Table Storage (for metadata)  
- Python packages listed in each function’s `requirements.txt`

## Installation & Deployment

1. **Clone the Repository:**  
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. **Azure Resources:**  
   - Create an **Azure Purview Account**.  
   - Create an **Azure Storage Account** with a container (e.g., `input-dlp-files`) and a quarantine container.  
   - Create an **Azure Service Bus** namespace and queue `dlp-alerts`.  
   - Create an **Azure Logic App** for quarantine workflow.  
   - Create **Function Apps** for:
     - Blob-triggered scan  
     - Service Bus trigger  
     - PCI remediation  
     - Fake-data generator (optional)

3. **Configure Application Settings:**  
   In each Function App’s **Configuration → Application settings**, add:

   | Name                           | Description                                  |
   |--------------------------------|----------------------------------------------|
   | `AZURE_CLIENT_ID`              | Service Principal (App) client ID            |
   | `AZURE_CLIENT_SECRET`          | Service Principal client secret              |
   | `AZURE_TENANT_ID`              | Azure AD Tenant ID                           |
   | `PURVIEW_ACCOUNT`              | Purview account name (no suffix)            |
   | `PURVIEW_DATASOURCE_NAME`      | Purview data source (e.g., ADLS Gen2 name)   |
   | `PURVIEW_COLLECTION_NAME`      | Purview collection reference name            |
   | `STORAGE_ACCOUNT_NAME`         | Data Lake Storage account name               |
   | `SERVICEBUS_CONNECTION_STRING` | Connection string for Service Bus queue      |
   | `LOG_ANALYTICS_WORKSPACE_ID`   | (If using custom queries)                    |
   | `QUARANTINE_CONTAINER_NAME`    | Quarantine blob container                    |

4. **Deploy via GitHub Actions:**  
   Ensure your **GitHub repo secrets** map to the above variables, then let the workflows auto-deploy:
   - `.github/workflows/main_purviewblobtrigger.yml`
   - `.github/workflows/main_triggerpurviewscan.yml`
   - `.github/workflows/main_pci100.yml`

5. **Manual Deployment (Optional):**  
   ```bash
   cd purviewblobtrigger
   func azure functionapp publish <BlobTriggerAppName>
   ```

## SQL Query for Log Analytics
```sql
PurviewDataSensitivityLogs
| where TimeGenerated > ago(10m)
| where Classification has_any ("Credit Card Number", "MICROSOFT.FINANCIAL", "MICROSOFT.PERSONAL")
| extend containerPath = split(AssetPath, "/")[-2]
| where containerPath == "input-dlp-files"  // input-dlp-files is the name of the source blob
| project 
    AssetName,
    AssetPath,
    Classification,
    TimeGenerated
```

## Repository Structure
```
.
├── .github/                      # CI/CD workflows
│   ├── main_pci100.yml
│   ├── main_purviewblobtrigger.yml
│   └── main_triggerpurviewscan.yml
├── fake_data_generator/          # Python function to create fake customer data
│   ├── generate_data.py
│   └── requirements.txt
├── pciremediation/               # Azure Function for PCI remediation
│   ├── function_app.py
│   ├── host.json
│   └── requirements.txt
├── purviewblobtrigger/           # Azure Function for Blob-triggered scans
│   ├── function_app.py
│   ├── host.json
│   └── requirements.txt
├── triggerpurviewscan/           # Azure Function for Service Bus-triggered scans
│   ├── function_app.py
│   ├── host.json
│   └── requirements.txt
├── AzureE2EDLP.drawio            # Architecture diagram
└── README.md                     # (This file)
```

## Security & Secrets Management
- **Move all hardcoded UUIDs** and keys into **Application Settings** or **Azure Key Vault**.  
- **Rotate any exposed credentials** immediately.  
- Use **Managed Identity** where possible to avoid managing client secrets.

---

**Happy scanning!**
**
