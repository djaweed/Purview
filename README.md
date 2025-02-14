This project implements an automated data classification and redaction workflow based on PCI (Payment Card Industry) standards. When a file is uploaded to an Azure Blob Storage container, a series of Azure services are triggered to classify, quarantine, and redact the data, while routing metadata and notifications accordingly. This can be used for a downstream application or a standalone. In this repository, it also includes a python function to create fake customer data to experiment based on your needs.

## Workflow Overview

1. **File Upload:**  
   A file is uploaded to the primary Azure Blob Storage container.

2. **Blob Trigger:**  
   The upload triggers an Azure Function which sends file details to an Azure Service Bus queue.

3. **Service Bus Processing:**  
   A second Azure Function, listening on the Service Bus, processes the message and triggers an Azure Purview scan for PCI classification.

4. **Purview Alert:**  
   If sensitive PCI data is detected, Purview raises an alert from a log analytics custom query that triggers a Logic App.

5. **Quarantine Process:**  
   The Logic App copies the file from the original blob storage to a quarantine blob storage.

6. **Data Redaction:**  
   An Azure Function then redacts the sensitive data in the file. This function also updates a metadata table and sends a message to another Service Bus.

7. **Queue Routing & Notifications:**  
   - **Success:** The file is routed to a "successful" queue if redaction is successful.  
   - **Failure:** If redaction fails, the file is routed to a "failure" queue and an email notification is sent using Azure Communication Service.

## Important Things to Note

At the data catalog level, you have to grant permissions, these aren't inherited from the resource group level or purview application level to make the API work.

##Learning Improvements

It took a while to get the purview API working, I had to reverse engineer the API calls from dev tools in the browser, Microsoft's Documentation is still not up to date regarding the new Purview.

If you use python v2, you need to use functions and decorators, you don't need to create a funciton.json file, Azure will do it for you. If you use python v1 then you need to use bindings and manually create a function.json. 

This was a deployed with a CI/CD pipeline so make sure you edit your .yml CI/CD workflow in the code once you connect your github to the function.

Appropriate variables need to be set in the Azure Function Application Settings, such as the correct connection strings, names, variables, etc.

## Prerequisites

- **Python 3.11**
- An Azure account with the following services configured:
  - Azure Blob Storage (for both initial and quarantine containers)
  - Azure Service Bus
  - Azure Purview
  - Azure Logic Apps
  - Azure Communication Service
  - Azure Table Storage (for storing metadata)
- Required Python packages (listed in `requirements.txt`)

## Installation

1. **Clone the Repository:**
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   
2. **SQL Query for Log Analytics**

```sql
PurviewDataSensitivityLogs
| where TimeGenerated > ago(10m)
| where Classification has_any ("Credit Card Number", "MICROSOFT.FINANCIAL", "MICROSOFT.PERSONAL")
| extend containerPath = split(AssetPath, "/")[-2]
| where containerPath == "input-dlp-files" #input-dlp-files is the name of the source blob
| project 
    AssetName,
    AssetPath,
    Classification,
    TimeGenerated
```
