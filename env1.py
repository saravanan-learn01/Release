#!/usr/bin/env python3
"""
Azure DevOps Release Pipeline Environment Creator
Version: 1.0 - Combined Simplifier + Environment Creator

This script:
1. Reads original release pipeline JSON files
2. Extracts environment information (ALL environments, even without approvals/gates)
3. Creates/updates environments in Azure DevOps with their approvals and gates
"""

import json
import os
import sys
import argparse
import base64
import requests
from pathlib import Path
import datetime
from typing import Dict, Any, List, Optional

# ============================================================================
# ENVIRONMENT CREATION FUNCTIONS (from environment.py)
# ============================================================================

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
        sys.exit(1)

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

def add_approval_check(org, project, headers, env_id, env_name, approvers_data, approval_options=None):
    """Sends the POST request to add the approval check to the environment."""
    
    if not approvers_data:
        print(f"    [SKIP] No approvers to add for '{env_name}'")
        return
    
    # Extract approver IDs
    approver_ids = [app["id"] for app in approvers_data]
    
    # Check if approval already exists and delete it
    existing_checks = get_existing_checks(org, project, headers, env_id)
    for check in existing_checks:
        if check.get("type", {}).get("name") == "Approval":
            if delete_check(org, project, headers, check["id"]):
                print(f"    [CLEANUP] Removed existing approval from '{env_name}'")
    
    # Create new approval
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
    # Format the approvers array as required by the API
    approvers_payload = [{"id": str(app_id)} for app_id in approver_ids]
    
    # Use approval options if available
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
            print(f"    [SUCCESS] Added {len(approver_ids)} approver(s) to environment '{env_name}'.")
            for app in approvers_data:
                print(f"             - {app.get('displayName', 'Unknown')} ({app.get('email', 'No email')})")
        else:
            print(f"    [FAILED] Approval for '{env_name}': {response.status_code} - {response.text}")
            
    except requests.exceptions.RequestException as e:
        print(f"    [ERROR] Failed to add approval: {e}")

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

def add_query_work_items_gate(org, project, headers, env_id, env_name, gate_info, timeout):
    """Adds Query Work Items gate to environment."""
    task_id = gate_info.get("taskId")
    task_name = gate_info.get("name", "Query Work Items")
    inputs = gate_info.get("inputs", {})
    
    print(f"      Adding Query Work Items gate...")
    
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
                "version": gate_info.get("version", "0.*")
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
            print(f"        [SUCCESS] Query Work Items gate added")
            return True
        else:
            print(f"        [FAILED] Query Work Items gate: {response.status_code}")
            return False
    except Exception as e:
        print(f"        [ERROR] Failed to add Query Work Items gate: {e}")
        return False

def add_invoke_rest_api_gate(org, project, headers, env_id, env_name, gate_info, timeout):
    """Adds Invoke REST API gate to environment."""
    task_id = gate_info.get("taskId")
    task_name = gate_info.get("name", "Invoke REST API")
    inputs = gate_info.get("inputs", {})
    
    print(f"      Adding Invoke REST API gate: '{task_name}'...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("connectedServiceName")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"        [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
    # Parse headers if they're a string
    headers_input = inputs.get("headers", "{}")
    if isinstance(headers_input, str):
        try:
            cleaned_headers = headers_input.replace('\n', '').replace('\r', '')
            headers_input = json.loads(cleaned_headers)
        except:
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
                "name": task_name,
                "version": gate_info.get("version", "1.*")
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
            print(f"        [SUCCESS] Invoke REST API gate added")
            return True
        else:
            print(f"        [FAILED] Invoke REST API gate: {response.status_code}")
            return False
    except Exception as e:
        print(f"        [ERROR] Failed to add Invoke REST API gate: {e}")
        return False

def add_check_policy_compliance_gate(org, project, headers, env_id, env_name, gate_info, timeout):
    """Adds Check Policy Compliance gate to environment."""
    task_id = gate_info.get("taskId")
    task_name = gate_info.get("name", "Check Policy Compliance")
    inputs = gate_info.get("inputs", {})
    
    print(f"      Adding Check Policy Compliance gate...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("ConnectedServiceName")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"        [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
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
                "version": gate_info.get("version", "0.*")
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
            print(f"        [SUCCESS] Check Policy Compliance gate added")
            return True
        else:
            print(f"        [FAILED] Check Policy Compliance gate: {response.status_code}")
            return False
    except Exception as e:
        print(f"        [ERROR] Failed to add Check Policy Compliance gate: {e}")
        return False

def add_azure_monitor_alerts_gate(org, project, headers, env_id, env_name, gate_info, timeout):
    """Adds Query Azure Monitor alerts gate to environment."""
    task_name = gate_info.get("name", "Query Azure Monitor alerts")
    inputs = gate_info.get("inputs", {})
    
    print(f"      Adding Query Azure Monitor alerts gate...")
    
    # Verify service connection exists
    service_conn_id = inputs.get("connectedServiceNameARM")
    if service_conn_id:
        if not verify_service_connection(org, project, headers, service_conn_id):
            print(f"        [WARNING] Service connection {service_conn_id} not found. Gate may not work.")
    
    AZURE_MONITOR_GATE_TYPE_ID = "C8B0C5A2-9F4E-4C7E-9F0A-8A5F2A1B3C4D"
    
    url = f"https://dev.azure.com/{org}/{project}/_apis/pipelines/checks/configurations?api-version=7.1-preview.1"
    
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
            print(f"        [SUCCESS] Query Azure Monitor alerts gate added")
            return True
        else:
            print(f"        [FAILED] Query Azure Monitor alerts gate: {response.status_code}")
            return False
    except Exception as e:
        print(f"        [ERROR] Failed to add Query Azure Monitor alerts gate: {e}")
        return False

def process_gates(org, project, headers, env_id, env_name, gates_config, gate_type):
    """Process all gates and create them in the environment."""
    if not gates_config or not gates_config.get("enabled", False):
        return 0
    
    timeout = gates_config.get("timeout", 1440)
    sampling = gates_config.get("samplingInterval", 15)
    stabilization = gates_config.get("stabilizationTime", 5)
    
    print(f"    [GATES] Adding {gate_type.upper()}-deployment gates to '{env_name}'")
    print(f"            Timeout: {timeout}min, Sampling: {sampling}min, Stabilization: {stabilization}min")
    
    gates = gates_config.get("gates", [])
    gate_count = 0
    
    for gate_info in gates:
        task_id = gate_info.get("taskId")
        task_name = gate_info.get("name", "Unknown")
        
        print(f"      Processing gate: {task_name} (ID: {task_id})")
        
        # Route to appropriate gate handler based on task ID
        if task_id == "f1e4b0e6-017e-4819-8a48-ef19ae96e289":  # Query Work Items
            if add_query_work_items_gate(org, project, headers, env_id, env_name, gate_info, timeout):
                gate_count += 1
        elif task_id == "9c3e8943-130d-4c78-ac63-8af81df62dfb":  # Invoke REST API
            if add_invoke_rest_api_gate(org, project, headers, env_id, env_name, gate_info, timeout):
                gate_count += 1
        elif task_id == "8ba74703-e94f-4a35-814e-fc21f44578a2":  # Check Policy Compliance
            if add_check_policy_compliance_gate(org, project, headers, env_id, env_name, gate_info, timeout):
                gate_count += 1
        elif task_id == "99a72e7f-25e4-4576-bf38-22a42b995ed8":  # Query Azure Monitor alerts
            if add_azure_monitor_alerts_gate(org, project, headers, env_id, env_name, gate_info, timeout):
                gate_count += 1
        else:
            print(f"        [SKIPPED] Unknown gate type: {task_name}")
    
    print(f"        [SUMMARY] Added {gate_count} gate(s) to '{env_name}'")
    return gate_count

# ============================================================================
# SIMPLIFIER FUNCTIONS (from simplify.py)
# ============================================================================

def safe_get(data, *keys, default=None):
    """Safely navigate through nested dictionaries."""
    current = data
    for key in keys:
        if current is None or not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current

def extract_approvers(approvals_data: Dict[str, Any]) -> List[Dict[str, str]]:
    """Extract approver IDs from approvals data"""
    approvers = []
    
    if not approvals_data:
        return approvers
    
    for approval in approvals_data.get("approvals", []):
        # Skip automated approvals
        if not approval.get("isAutomated", True):
            approver = approval.get("approver", {})
            if approver and "id" in approver:
                approvers.append({
                    "id": approver["id"],
                    "displayName": approver.get("displayName", ""),
                    "email": approver.get("uniqueName", "")
                })
    
    return approvers

def extract_approval_options(approvals_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract approval options"""
    if not approvals_data:
        return None
    
    options = approvals_data.get("approvalOptions", {})
    if options:
        return {
            "requiredApproverCount": options.get("requiredApproverCount"),
            "timeoutInMinutes": options.get("timeoutInMinutes", 43200),
            "releaseCreatorCanBeApprover": options.get("releaseCreatorCanBeApprover", False),
            "executionOrder": options.get("executionOrder", "beforeGates")
        }
    return None

def extract_gates(gates_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extract gate information"""
    if not gates_data:
        return None
    
    gates_options = gates_data.get("gatesOptions")
    if not gates_options or not gates_options.get("isEnabled", False):
        return None
    
    gates_info = {
        "enabled": True,
        "timeout": gates_options.get("timeout", 1440),
        "samplingInterval": gates_options.get("samplingInterval", 15),
        "stabilizationTime": gates_options.get("stabilizationTime", 5),
        "gates": []
    }
    
    # Extract individual gates
    for gate in gates_data.get("gates", []):
        for task in gate.get("tasks", []):
            gate_info = {
                "taskId": task.get("taskId"),
                "name": task.get("name"),
                "version": task.get("version"),
                "enabled": task.get("enabled", True),
                "inputs": task.get("inputs", {})
            }
            gates_info["gates"].append(gate_info)
    
    return gates_info if gates_info["gates"] else None

def extract_environment_config(env):
    """Extract environment configuration from original JSON structure"""
    try:
        env_name = env.get("name", "")
        if not env_name:
            return None
        
        env_info = {
            "name": env_name,
            "rank": env.get("rank", 0),
            "preDeployApprovals": {
                "approvers": [],
                "options": None
            },
            "postDeployApprovals": {
                "approvers": [],
                "options": None
            },
            "preDeploymentGates": None,
            "postDeploymentGates": None,
            "has_configuration": False
        }
        
        # Extract pre-deployment approvals
        pre_approvals = env.get("preDeployApprovals", {})
        pre_approvers = extract_approvers(pre_approvals)
        if pre_approvers:
            env_info["preDeployApprovals"]["approvers"] = pre_approvers
            env_info["preDeployApprovals"]["options"] = extract_approval_options(pre_approvals)
            env_info["has_configuration"] = True
        
        # Extract post-deployment approvals
        post_approvals = env.get("postDeployApprovals", {})
        post_approvers = extract_approvers(post_approvals)
        if post_approvers:
            env_info["postDeployApprovals"]["approvers"] = post_approvers
            env_info["postDeployApprovals"]["options"] = extract_approval_options(post_approvals)
            env_info["has_configuration"] = True
        
        # Extract pre-deployment gates
        pre_gates = extract_gates(env.get("preDeploymentGates", {}))
        if pre_gates:
            env_info["preDeploymentGates"] = pre_gates
            env_info["has_configuration"] = True
        
        # Extract post-deployment gates
        post_gates = extract_gates(env.get("postDeploymentGates", {}))
        if post_gates:
            env_info["postDeploymentGates"] = post_gates
            env_info["has_configuration"] = True
        
        return env_info
        
    except Exception as e:
        print(f"      Warning: Error processing environment {env.get('name', 'unknown')}: {str(e)}")
        return None

# ============================================================================
# MAIN PROCESSING FUNCTION
# ============================================================================

def process_and_create_environments(
    input_folder: str,
    org: str,
    project: str,
    pat_file: str,
    create_missing: bool = True,
    include_all: bool = True
):
    """Process JSON files and create/update environments in Azure DevOps"""
    
    # Setup auth
    headers = get_auth_headers(pat_file)
    
    # Get live environments
    print("\n--- Fetching live environments from Azure DevOps ---")
    live_env_map = get_live_environments(org, project, headers)
    
    # Get all JSON files
    input_folder = os.path.abspath(input_folder)
    json_files = list(Path(input_folder).glob("*.json"))
    
    if not json_files:
        print(f"\n❌ No JSON files found in: {input_folder}")
        return
    
    print(f"\n✅ Found {len(json_files)} JSON file(s) to process")
    print(f"📂 Input folder: {input_folder}")
    print(f"📋 Mode: {'Including ALL environments' if include_all else 'Only environments with approvals/gates'}")
    
    # Statistics
    total_envs_processed = 0
    total_envs_created = 0
    total_approvals_added = 0
    total_gates_added = 0
    environments_processed = set()
    
    for json_file in json_files:
        print(f"\n{'='*60}")
        print(f"Processing file: {json_file.name}...")
        print(f"{'='*60}")
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON file {json_file.name}: {e}")
            continue
        
        pipeline_name = data.get("name", "Unknown")
        pipeline_id = data.get("id", "N/A")
        print(f"Pipeline: {pipeline_name} (ID: {pipeline_id})")
        
        environments = data.get("environments", [])
        envs_with_config = 0
        
        for env in environments:
            env_config = extract_environment_config(env)
            if not env_config:
                continue
            
            env_name = env_config["name"]
            env_key = env_name.lower()
            
            print(f"\n  {'─'*50}")
            print(f"  Processing Environment: '{env_name}'")
            print(f"  {'─'*50}")
            
            environments_processed.add(env_name)
            
            # Display configuration summary
            if env_config["preDeployApprovals"]["approvers"]:
                print(f"    Pre-deploy approvers: {len(env_config['preDeployApprovals']['approvers'])}")
            if env_config["postDeployApprovals"]["approvers"]:
                print(f"    Post-deploy approvers: {len(env_config['postDeployApprovals']['approvers'])}")
            if env_config["preDeploymentGates"]:
                print(f"    Pre-deployment gates: {len(env_config['preDeploymentGates'].get('gates', []))}")
            if env_config["postDeploymentGates"]:
                print(f"    Post-deployment gates: {len(env_config['postDeploymentGates'].get('gates', []))}")
            
            if not env_config["has_configuration"]:
                print(f"    [NOTE] No approvals or gates configured for this environment")
                if not include_all:
                    print(f"    [SKIP] Skipping environment without configuration")
                    continue
            
            # Handle environment creation/update
            if env_key in live_env_map:
                env_id = live_env_map[env_key]["id"]
                print(f"    Environment exists (ID: {env_id})")
                total_envs_processed += 1
                envs_with_config += 1 if env_config["has_configuration"] else 0
                
            elif create_missing:
                print(f"    Environment doesn't exist - creating...")
                env_id = create_environment(org, project, headers, env_name)
                if env_id:
                    total_envs_created += 1
                    total_envs_processed += 1
                    envs_with_config += 1 if env_config["has_configuration"] else 0
                    live_env_map[env_key] = {"id": env_id, "name": env_name}
                else:
                    continue
            else:
                print(f"    [WARNING] Environment '{env_name}' does not exist. Use --create-envs to auto-create.")
                continue
            
            # Add approvals if any
            if env_config["preDeployApprovals"]["approvers"]:
                add_approval_check(
                    org, project, headers, env_id, env_name,
                    env_config["preDeployApprovals"]["approvers"],
                    env_config["preDeployApprovals"]["options"]
                )
                total_approvals_added += 1
            
            if env_config["postDeployApprovals"]["approvers"]:
                add_approval_check(
                    org, project, headers, env_id, env_name,
                    env_config["postDeployApprovals"]["approvers"],
                    env_config["postDeployApprovals"]["options"]
                )
                total_approvals_added += 1
            
            # Add gates if any
            if env_config["preDeploymentGates"]:
                gate_count = process_gates(
                    org, project, headers, env_id, env_name,
                    env_config["preDeploymentGates"], "PRE"
                )
                total_gates_added += gate_count
            
            if env_config["postDeploymentGates"]:
                gate_count = process_gates(
                    org, project, headers, env_id, env_name,
                    env_config["postDeploymentGates"], "POST"
                )
                total_gates_added += gate_count
    
    # Print final summary
    print(f"\n{'='*60}")
    print("MIGRATION SUMMARY")
    print(f"{'='*60}")
    print(f"Unique environments processed: {len(environments_processed)}")
    print(f"Environment instances processed: {total_envs_processed}")
    print(f"New environments created: {total_envs_created}")
    print(f"Approval checks added: {total_approvals_added}")
    print(f"Gates added: {total_gates_added}")
    print(f"\nEnvironments configured:")
    for env_name in sorted(environments_processed):
        print(f"  - {env_name}")
    print(f"{'='*60}")

# ============================================================================
# COMMAND LINE INTERFACE
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description='Extract environment info from Azure DevOps release pipelines AND create them',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s C:\\Users\\John\\Documents\\json_files --org myorg --project myproject --pat-file pat.txt
  %(prog)s /home/user/documents/json_files -o custom_output --org myorg --project myproject --pat-file pat.txt --create-envs

This script:
1. Reads original release pipeline JSON files
2. Extracts environment configurations
3. Creates/updates environments in Azure DevOps with their approvals and gates
        """
    )
    
    # Input folder argument
    parser.add_argument(
        'input_folder',
        help='Path to folder containing original release pipeline JSON files'
    )
    
    # Azure DevOps arguments
    parser.add_argument(
        '--org',
        required=True,
        help='Azure DevOps Organization name'
    )
    
    parser.add_argument(
        '--project',
        required=True,
        help='Azure DevOps Project name'
    )
    
    parser.add_argument(
        '--pat-file',
        required=True,
        help='Path to the text file containing your PAT'
    )
    
    # Optional arguments
    parser.add_argument(
        '--create-envs',
        action='store_true',
        help='Create missing environments automatically'
    )
    
    parser.add_argument(
        '--skip-empty',
        action='store_true',
        help='Skip environments without approvals or gates (default: include all)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show verbose output'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🏭 Azure DevOps Release Pipeline Environment Creator")
    print("="*60)
    print(f"Organization: {args.org}")
    print(f"Project: {args.project}")
    print(f"Input folder: {args.input_folder}")
    print(f"Create missing envs: {args.create_envs}")
    print(f"Include empty envs: {not args.skip_empty}")
    print("="*60)
    
    if not os.path.exists(args.input_folder):
        print(f"\n❌ Error: Input folder does not exist: {args.input_folder}")
        sys.exit(1)
    
    if not os.path.isdir(args.input_folder):
        print(f"\n❌ Error: Path is not a directory: {args.input_folder}")
        sys.exit(1)
    
    if not os.path.exists(args.pat_file):
        print(f"\n❌ Error: PAT file does not exist: {args.pat_file}")
        sys.exit(1)
    
    try:
        process_and_create_environments(
            input_folder=args.input_folder,
            org=args.org,
            project=args.project,
            pat_file=args.pat_file,
            create_missing=args.create_envs,
            include_all=not args.skip_empty
        )
        print(f"\n✨ Migration complete!")
    except Exception as e:
        print(f"\n❌ Error during processing: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()