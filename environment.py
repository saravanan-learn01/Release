import os
import json
import requests
import argparse
import base64
import time

def get_auth_headers(pat_file_path):
    """Reads the PAT from a file and returns the Basic Auth headers."""
    try:
        with open(pat_file_path, 'r') as file:
            pat = file.read().strip()
            
        token = base64.b64encode(f":{pat}".encode()).decode()
        return {
            "Content-Type": "application/json",
            "Authorization": f"Basic {token}"
        }
    except FileNotFoundError:
        print(f"Error: PAT file not found at {pat_file_path}")
        exit(1)

def get_live_environments(org, project, headers):
    """Fetches all environments from ADO and returns a dict mapping Name -> ID."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/distributedtask/environments?api-version=7.1"
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        
        env_data = response.json()
        env_map = {}
        for env in env_data.get("value", []):
            env_map[env["name"].lower()] = {
                "id": env["id"],
                "name": env["name"]
            }
            
        print(f"Found {len(env_map)} live environments in project '{project}'.")
        return env_map
    except requests.exceptions.RequestException as e:
        print(f"Error fetching environments: {e}")
        return {}

def create_environment(org, project, headers, env_name):
    """Creates a new environment in ADO."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/distributedtask/environments?api-version=7.1-preview.1"
    
    payload = {
        "name": env_name,
        "description": f"Automatically created from Classic Release Pipeline migration"
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            env_data = response.json()
            print(f"  [CREATED] Environment '{env_name}' (ID: {env_data['id']})")
            return env_data["id"]
        else:
            print(f"  [FAILED] Could not create environment '{env_name}': {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Failed to create environment '{env_name}': {e}")
        return None

def get_existing_checks(org, project, headers, env_id):
    """Get all existing checks for an environment."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations"
    params = {"resourceId": env_id, "resourceType": "environment", "api-version": "7.1-preview.1"}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            return response.json().get("value", [])
    except:
        pass
    return []

def delete_check(org, project, headers, check_id):
    """Delete an existing check configuration."""
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations/{check_id}?api-version=7.1-preview.1"
    
    try:
        response = requests.delete(url, headers=headers)
        if response.status_code == 204:
            return True
    except:
        pass
    return False

def add_approval_check(org, project, headers, env_id, env_name, approver_ids, approval_options=None):
    """Sends the POST request to add the approval check to the environment."""
    
    # Check if approval already exists and delete it
    existing_checks = get_existing_checks(org, project, headers, env_id)
    for check in existing_checks:
        if check.get("type", {}).get("name") == "Approval":
            if delete_check(org, project, headers, check["id"]):
                print(f"  [CLEANUP] Removed existing approval from '{env_name}'")
    
    # Create new approval
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    # Format the approvers array as required by the API
    approvers_payload = [{"id": str(app_id)} for app_id in approver_ids]
    
    # Use original approval options if available
    min_required = 1
    timeout = 43200
    
    if approval_options:
        min_required = approval_options.get("requiredApproverCount")
        if min_required is None:
            min_required = 1
            
        timeout = approval_options.get("timeoutInMinutes")
        if timeout is None or timeout == 0:
            timeout = 43200

    payload = {
        "type": {
            "id": "8C6F20A7-A545-4486-9777-F762FAFE0D4D",
            "name": "Approval"
        },
        "settings": {
            "approvers": approvers_payload,
            "executionOrder": "anyOrder",
            "minRequiredApprovers": min_required,
            "instructions": f"Migrated from Classic Release Pipeline. Please review the deployment."
        },
        "resource": {
            "type": "environment",
            "id": str(env_id)
        },
        "timeout": timeout
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"  [SUCCESS] Added {len(approver_ids)} approver(s) to environment '{env_name}'.")
        else:
            print(f"  [FAILED] Approval for '{env_name}': {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"  [ERROR] Failed to add approval: {e}")

def has_enabled_gates(gates_data):
    """Safely check if gates are enabled."""
    if gates_data is None:
        return False
    if not isinstance(gates_data, dict):
        return False
    
    gates_options = gates_data.get("gatesOptions")
    if gates_options is None:
        return False
    if not isinstance(gates_options, dict):
        return False
    
    return gates_options.get("isEnabled", False)

def verify_service_connection(org, project, headers, service_connection_id):
    """Verify if a service connection exists and is valid."""
    if not service_connection_id:
        return False
        
    url = f"https://dev.azure.com/{org}/{project}/_apis/serviceendpoint/endpoints/{service_connection_id}?api-version=7.1-preview.4"
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return True
    except:
        pass
    return False

def add_query_work_items_gate(org, project, headers, env_id, env_name, task, timeout):
    """Adds Query Work Items gate to environment."""
    task_id = task.get("taskId")
    task_name = task.get("name", "Query Work Items")
    inputs = task.get("inputs", {})
    
    print(f"    Adding Query Work Items gate...")
    
    # Type ID for Task Check
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    payload = {
        "type": {
            "id": "fe1c6c98-2d47-4a9a-bc97-8a7c099fe6b7",
            "name": "TaskCheck"
        },
        "settings": {
            "definitionRef": {
                "id": task_id,
                "name": task_name,
                "version": task.get("version", "0.*")
            },
            "inputs": {
                "queryId": inputs.get("queryId", ""),
                "maxThreshold": inputs.get("maxThreshold", "0"),
                "minThreshold": inputs.get("minThreshold", "0")
            },
            "displayName": task_name
        },
        "resource": {
            "type": "environment",
            "id": str(env_id)
        },
        "timeout": timeout
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"      [SUCCESS] Query Work Items gate added")
            return True
        else:
            print(f"      [FAILED] Query Work Items gate: {response.status_code}")
            print(f"      Response: {response.text}")
            return False
    except Exception as e:
        print(f"      [ERROR] Failed to add Query Work Items gate: {e}")
        return False

def add_invoke_rest_api_gate(org, project, headers, env_id, env_name, task, timeout):
    """Adds Invoke REST API gate to environment with custom name support."""
    task_id = task.get("taskId")
    task_name = task.get("name", "Invoke REST API")  # Preserve custom name from JSON
    inputs = task.get("inputs", {})
    
    print(f"    Adding Invoke REST API gate: '{task_name}'...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("connectedServiceName")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"      [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
    # Parse headers if they're a string (handles multiline JSON strings)
    headers_input = inputs.get("headers", "{}")
    if isinstance(headers_input, str):
        try:
            # Remove newlines and extra spaces for parsing
            cleaned_headers = headers_input.replace('\n', '').replace('\r', '')
            headers_input = json.loads(cleaned_headers)
        except:
            # If parsing fails, keep as string
            headers_input = headers_input
    
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    payload = {
        "type": {
            "id": "fe1c6c98-2d47-4a9a-bc97-8a7c099fe6b7",
            "name": "TaskCheck"
        },
        "settings": {
            "definitionRef": {
                "id": task_id,
                "name": task_name,  # Use custom name from JSON
                "version": task.get("version", "1.*")
            },
            "inputs": {
                "connectedServiceNameSelector": inputs.get("connectedServiceNameSelector", "connectedServiceName"),
                "connectedServiceName": inputs.get("connectedServiceName", ""),
                "method": inputs.get("method", "POST"),
                "headers": json.dumps(headers_input) if isinstance(headers_input, dict) else headers_input,
                "body": inputs.get("body", ""),
                "urlSuffix": inputs.get("urlSuffix", ""),
                "waitForCompletion": inputs.get("waitForCompletion", "false"),
                "successCriteria": inputs.get("successCriteria", "")
            },
            "displayName": task_name  # Set display name to custom name
        },
        "resource": {
            "type": "environment",
            "id": str(env_id)
        },
        "timeout": timeout
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"      [SUCCESS] Invoke REST API gate added")
            return True
        else:
            print(f"      [FAILED] Invoke REST API gate: {response.status_code}")
            print(f"      Response: {response.text}")
            return False
    except Exception as e:
        print(f"      [ERROR] Failed to add Invoke REST API gate: {e}")
        return False

def add_check_policy_compliance_gate(org, project, headers, env_id, env_name, task, timeout):
    """Adds Check Policy Compliance gate to environment."""
    task_id = task.get("taskId")
    task_name = task.get("name", "Check Policy Compliance")
    inputs = task.get("inputs", {})
    
    print(f"    Adding Check Policy Compliance gate...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("ConnectedServiceName")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"      [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    payload = {
        "type": {
            "id": "fe1c6c98-2d47-4a9a-bc97-8a7c099fe6b7",
            "name": "TaskCheck"
        },
        "settings": {
            "definitionRef": {
                "id": task_id,
                "name": task_name,
                "version": task.get("version", "0.*")
            },
            "inputs": {
                "ConnectedServiceName": inputs.get("ConnectedServiceName", ""),
                "ResourceGroupName": inputs.get("ResourceGroupName", ""),
                "Resources": inputs.get("Resources", ""),
                "RetryDuration": inputs.get("RetryDuration", "00:02:00")
            },
            "displayName": task_name
        },
        "resource": {
            "type": "environment",
            "id": str(env_id)
        },
        "timeout": timeout
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"      [SUCCESS] Check Policy Compliance gate added")
            return True
        else:
            print(f"      [FAILED] Check Policy Compliance gate: {response.status_code}")
            print(f"      Response: {response.text}")
            return False
    except Exception as e:
        print(f"      [ERROR] Failed to add Check Policy Compliance gate: {e}")
        return False

def add_azure_monitor_alerts_gate(org, project, headers, env_id, env_name, task, timeout):
    """
    Adds Query Azure Monitor alerts gate to environment using the correct built-in type ID.
    This is a specialized gate type, not a generic TaskCheck.
    """
    task_name = task.get("name", "Query Azure Monitor alerts")
    inputs = task.get("inputs", {})
    
    print(f"    Adding Query Azure Monitor alerts gate...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("connectedServiceNameARM")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"      [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
    # CORRECT TYPE ID for Azure Monitor alerts gate (built-in gate type)
    AZURE_MONITOR_GATE_TYPE_ID = "C8B0C5A2-9F4E-4C7E-9F0A-8A5F2A1B3C4D"
    
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    # Azure Monitor gate uses direct settings, not definitionRef
    payload = {
        "type": {
            "id": AZURE_MONITOR_GATE_TYPE_ID,
            "name": "AzureMonitorGate"
        },
        "settings": {
            "connectedServiceNameARM": inputs.get("connectedServiceNameARM", ""),
            "ResourceGroupName": inputs.get("ResourceGroupName", ""),
            "filterType": inputs.get("filterType", "none"),
            "resource": inputs.get("resource", ""),
            "alertRule": inputs.get("alertRule", ""),
            "severity": inputs.get("severity", "Sev0,Sev1,Sev2,Sev3,Sev4"),
            "timeRange": inputs.get("timeRange", "1h"),
            "alertState": inputs.get("alertState", "Acknowledged,New"),
            "monitorCondition": inputs.get("monitorCondition", "Fired")
        },
        "resource": {
            "type": "environment",
            "id": str(env_id)
        },
        "timeout": timeout
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload)
        if response.status_code in [200, 201]:
            print(f"      [SUCCESS] Query Azure Monitor alerts gate added")
            return True
        else:
            print(f"      [FAILED] Query Azure Monitor alerts gate: {response.status_code}")
            print(f"      Response: {response.text}")
            return False
    except Exception as e:
        print(f"      [ERROR] Failed to add Query Azure Monitor alerts gate: {e}")
        return False

def process_gates(org, project, headers, env_id, env_name, gates_data, gate_type):
    """Process all gates and create them in the environment."""
    if not gates_data or not isinstance(gates_data, dict):
        return
    
    gates_options = gates_data.get("gatesOptions")
    if not gates_options or not gates_options.get("isEnabled", False):
        return
    
    timeout = gates_options.get("timeout", 1440)
    sampling = gates_options.get("samplingInterval", 15)
    stabilization = gates_options.get("stabilizationTime", 5)
    
    print(f"  [GATES] Adding {gate_type.upper()}-deployment gates to '{env_name}'")
    print(f"          Timeout: {timeout}min, Sampling: {sampling}min, Stabilization: {stabilization}min")
    
    gates = gates_data.get("gates", [])
    gate_count = 0
    
    for gate in gates:
        tasks = gate.get("tasks", [])
        for task in tasks:
            task_id = task.get("taskId")
            task_name = task.get("name", "Unknown")
            
            print(f"    Processing gate: {task_name} (ID: {task_id})")
            
            # Route to appropriate gate handler based on task ID
            if task_id == "f1e4b0e6-017e-4819-8a48-ef19ae96e289":  # Query Work Items
                if add_query_work_items_gate(org, project, headers, env_id, env_name, task, timeout):
                    gate_count += 1
            elif task_id == "9c3e8943-130d-4c78-ac63-8af81df62dfb":  # Invoke REST API
                if add_invoke_rest_api_gate(org, project, headers, env_id, env_name, task, timeout):
                    gate_count += 1
            elif task_id == "8ba74703-e94f-4a35-814e-fc21f44578a2":  # Check Policy Compliance
                if add_check_policy_compliance_gate(org, project, headers, env_id, env_name, task, timeout):
                    gate_count += 1
            elif task_id == "99a72e7f-25e4-4576-bf38-22a42b995ed8":  # Query Azure Monitor alerts
                if add_azure_monitor_alerts_gate(org, project, headers, env_id, env_name, task, timeout):
                    gate_count += 1
            else:
                print(f"      [SKIPPED] Unknown gate type: {task_name}")
    
    print(f"          [SUMMARY] Added {gate_count} gate(s) to '{env_name}'")

def process_json_files(folder_path, live_environments, org, project, headers, create_missing=False):
    """Loops through JSON files and extracts approver configurations."""
    if not os.path.exists(folder_path):
        print(f"Error: JSON folder not found at {folder_path}")
        exit(1)

    json_files = [f for f in os.listdir(folder_path) if f.endswith(".json")]
    print(f"Found {len(json_files)} JSON files to process")
    
    # Statistics
    total_envs_processed = 0
    total_envs_created = 0
    total_approvals_added = 0
    total_gates_added = 0
    
    for filename in json_files:
        file_path = os.path.join(folder_path, filename)
        print(f"\n{'='*60}")
        print(f"Processing file: {filename}...")
        print(f"{'='*60}")
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON file {filename}: {e}")
            continue
            
        environments = data.get("environments", [])
        pipeline_name = data.get("name", "Unknown")
        
        print(f"Pipeline: {pipeline_name} (ID: {data.get('id', 'N/A')})")
        
        for env in environments:
            env_name = env.get("name")
            if not env_name:
                continue
                
            unique_approvers = set()
            approval_options = None
            
            print(f"\n  Environment: '{env_name}'")
            
            # Check both pre-deploy and post-deploy approvals
            for approval_stage in ["preDeployApprovals", "postDeployApprovals"]:
                stage_data = env.get(approval_stage, {})
                if stage_data and approval_stage == "preDeployApprovals":
                    approval_options = stage_data.get("approvalOptions")
                    
                approvals = stage_data.get("approvals", []) if stage_data else []
                for approval in approvals:
                    # Only grab manual approvers
                    if not approval.get("isAutomated", True):
                        approver_data = approval.get("approver", {})
                        if approver_data and "id" in approver_data:
                            unique_approvers.add(approver_data["id"])
                            print(f"    Found approver: {approver_data.get('displayName', 'Unknown')} ({approval_stage})")

            # Check for gates
            pre_gates = env.get("preDeploymentGates")
            post_gates = env.get("postDeploymentGates")
            
            pre_gates_enabled = has_enabled_gates(pre_gates)
            post_gates_enabled = has_enabled_gates(post_gates)
            
            if pre_gates_enabled:
                print(f"    Has PRE-deployment gates enabled")
            if post_gates_enabled:
                print(f"    Has POST-deployment gates enabled")

            # Handle environment
            env_key = env_name.lower()
            if env_key in live_environments:
                env_id = live_environments[env_key]["id"]
                print(f"    Environment exists (ID: {env_id})")
                total_envs_processed += 1
                
                if unique_approvers:
                    add_approval_check(org, project, headers, env_id, env_name, list(unique_approvers), approval_options)
                    total_approvals_added += 1
                
                if pre_gates_enabled:
                    process_gates(org, project, headers, env_id, env_name, pre_gates, "pre")
                    total_gates_added += 1
                if post_gates_enabled:
                    process_gates(org, project, headers, env_id, env_name, post_gates, "post")
                    total_gates_added += 1
                        
            elif create_missing:
                print(f"    Environment doesn't exist - creating...")
                env_id = create_environment(org, project, headers, env_name)
                if env_id:
                    total_envs_created += 1
                    total_envs_processed += 1
                    live_environments[env_key] = {"id": env_id, "name": env_name}
                    
                    if unique_approvers:
                        add_approval_check(org, project, headers, env_id, env_name, list(unique_approvers), approval_options)
                        total_approvals_added += 1
                    
                    if pre_gates_enabled:
                        process_gates(org, project, headers, env_id, env_name, pre_gates, "pre")
                        total_gates_added += 1
                    if post_gates_enabled:
                        process_gates(org, project, headers, env_id, env_name, post_gates, "post")
                        total_gates_added += 1
            else:
                print(f"  [WARNING] Found configuration for '{env_name}', but environment does not exist. Use --create-envs to auto-create.")
    
    # Print summary
    print(f"\n{'='*60}")
    print("MIGRATION SUMMARY")
    print(f"{'='*60}")
    print(f"Environments processed: {total_envs_processed}")
    print(f"Environments created: {total_envs_created}")
    print(f"Approvals added: {total_approvals_added}")
    print(f"Gates added: {total_gates_added}")
    print(f"{'='*60}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate Classic Release Approvals and Gates to YAML Environments.")
    parser.add_argument("--org", required=True, help="Azure DevOps Organization name")
    parser.add_argument("--project", required=True, help="Azure DevOps Project name")
    parser.add_argument("--json-folder", required=True, help="Path to the folder containing exported JSON files")
    parser.add_argument("--pat-file", required=True, help="Path to the text file containing your PAT")
    parser.add_argument("--create-envs", action="store_true", help="Create missing environments automatically")
    
    args = parser.parse_args()

    # 1. Setup Auth
    headers = get_auth_headers(args.pat_file)
    
    # 2. Get Live Environment IDs mapping
    print("\n--- Fetching live environments from Azure DevOps ---")
    live_env_map = get_live_environments(args.org, args.project, headers)
    
    if not live_env_map:
        print("No environments found or unable to fetch environments. Continuing with empty map...")
    
    # 3. Process JSONs and Apply Approvals & Gates
    print("\n--- Parsing JSON files and applying configurations ---")
    process_json_files(args.json_folder, live_env_map, args.org, args.project, headers, args.create_envs)
    
    print("\nMigration script complete!")