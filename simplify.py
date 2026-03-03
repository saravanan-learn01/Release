#!/usr/bin/env python3
"""
Azure DevOps Release Pipeline JSON Simplifier
Version: 2.1 - Environment-Only Mode (Fixed type hints)

This script extracts ONLY environment information needed for environment.py:
- Environment names
- Approvers (pre and post deployment)
- Gates (pre and post deployment)
- Approval options (timeout, required approvers)

Output is optimized for use with environment.py migration script.
"""

import json
import os
import sys
import argparse
from pathlib import Path
import datetime
from typing import Dict, Any, List, Optional

def safe_get(data, *keys, default=None):
    """
    Safely navigate through nested dictionaries.
    Returns default if any key is missing or value is None.
    """
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

def simplify_for_environment(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract ONLY the environment information needed by environment.py
    """
    simplified = {
        "pipeline_info": {
            "name": input_data.get("name", ""),
            "id": input_data.get("id", ""),
            "path": input_data.get("path", "")
        },
        "environments": []
    }
    
    # Process each environment
    for env in input_data.get("environments", []):
        try:
            env_name = env.get("name", "")
            if not env_name:
                continue
            
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
                "postDeploymentGates": None
            }
            
            # Extract pre-deployment approvals
            pre_approvals = env.get("preDeployApprovals", {})
            pre_approvers = extract_approvers(pre_approvals)
            if pre_approvers:
                env_info["preDeployApprovals"]["approvers"] = pre_approvers
                env_info["preDeployApprovals"]["options"] = extract_approval_options(pre_approvals)
            
            # Extract post-deployment approvals
            post_approvals = env.get("postDeployApprovals", {})
            post_approvers = extract_approvers(post_approvals)
            if post_approvers:
                env_info["postDeployApprovals"]["approvers"] = post_approvers
                env_info["postDeployApprovals"]["options"] = extract_approval_options(post_approvals)
            
            # Extract pre-deployment gates
            pre_gates = extract_gates(env.get("preDeploymentGates", {}))
            if pre_gates:
                env_info["preDeploymentGates"] = pre_gates
            
            # Extract post-deployment gates
            post_gates = extract_gates(env.get("postDeploymentGates", {}))
            if post_gates:
                env_info["postDeploymentGates"] = post_gates
            
            # Only add environment if it has approvals or gates
            if (env_info["preDeployApprovals"]["approvers"] or 
                env_info["postDeployApprovals"]["approvers"] or
                env_info["preDeploymentGates"] or
                env_info["postDeploymentGates"]):
                simplified["environments"].append(env_info)
            
        except Exception as e:
            print(f"      Warning: Error processing environment {env.get('name', 'unknown')}: {str(e)}")
            continue
    
    return simplified

def process_folder(input_folder: str, output_base_folder: str = "output"):
    """
    Process all JSON files and create environment-only simplified versions.
    """
    input_folder = os.path.abspath(input_folder)
    
    # Create output folder for environment configs
    output_folder = os.path.join(output_base_folder, "environment_configs")
    output_folder = os.path.abspath(output_folder)
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    # Get all JSON files
    json_files = list(Path(input_folder).glob("*.json"))
    
    if not json_files:
        print(f"\n❌ No JSON files found in: {input_folder}")
        return
    
    print(f"\n✅ Found {len(json_files)} JSON file(s) to process")
    print(f"📂 Input folder: {input_folder}")
    print(f"📂 Output folder: {output_folder}\n")
    
    processed_files = 0
    files_with_environments = 0
    failed_files = []
    total_environments = 0
    
    for json_file in json_files:
        try:
            print(f"🔄 Processing: {json_file.name}...", end=" ", flush=True)
            
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Extract environment-only information
            simplified = simplify_for_environment(data)
            
            if simplified["environments"]:
                # Create output filename
                output_filename = json_file.stem + "_env_config.json"
                output_path = os.path.join(output_folder, output_filename)
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump(simplified, f, indent=2)
                
                env_count = len(simplified["environments"])
                total_environments += env_count
                files_with_environments += 1
                print(f"✅ ({env_count} environment(s))")
            else:
                print(f"⚠️  (No environments with approvals/gates)")
            
            processed_files += 1
            
        except json.JSONDecodeError as e:
            print("❌")
            print(f"     Error: Invalid JSON - {str(e)}")
            failed_files.append(f"{json_file.name} (Invalid JSON)")
        except Exception as e:
            print("❌")
            print(f"     Error: {str(e)}")
            failed_files.append(f"{json_file.name} ({str(e)})")
    
    # Create summary
    summary = {
        "processing_date": datetime.datetime.now().isoformat(),
        "input_folder": input_folder,
        "output_folder": output_folder,
        "total_files_processed": processed_files,
        "files_with_environments": files_with_environments,
        "total_environments_found": total_environments,
        "failed_files": failed_files
    }
    
    summary_path = os.path.join(output_folder, "environment_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    # Print summary
    print("\n" + "="*60)
    print("📊 ENVIRONMENT EXTRACTION SUMMARY")
    print("="*60)
    print(f"📍 Output folder: {output_folder}")
    print(f"📄 Files processed: {processed_files}")
    print(f"📋 Files with environments: {files_with_environments}")
    print(f"🌍 Total environments found: {total_environments}")
    
    if failed_files:
        print(f"\n❌ Failed files: {len(failed_files)}")
        for failed in failed_files[:5]:
            print(f"  • {failed}")
        if len(failed_files) > 5:
            print(f"  ... and {len(failed_files) - 5} more")
    
    print(f"\n📋 Summary file: {summary_path}")
    print("="*60)
    
    return output_folder

def main():
    parser = argparse.ArgumentParser(
        description='Extract environment information from Azure DevOps release pipelines',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s C:\\Users\\John\\Documents\\json_files
  %(prog)s /home/user/documents/json_files -o env_configs
  %(prog)s "C:\\My Pipelines\\json files" --output "C:\\Environment Configs"

This script extracts ONLY environment information (approvers and gates) 
needed for the environment.py migration script.
        """
    )
    
    parser.add_argument(
        'input_folder',
        help='Path to folder containing release pipeline JSON files'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='environment_output',
        help='Output folder name (default: environment_output)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show verbose output'
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🏭 Azure DevOps Environment Configuration Extractor")
    print("="*60)
    print("Extracts ONLY environment info for migration to YAML")
    print("="*60)
    
    if not os.path.exists(args.input_folder):
        print(f"\n❌ Error: Input folder does not exist: {args.input_folder}")
        sys.exit(1)
    
    if not os.path.isdir(args.input_folder):
        print(f"\n❌ Error: Path is not a directory: {args.input_folder}")
        sys.exit(1)
    
    try:
        output_folder = process_folder(args.input_folder, args.output)
        print(f"\n✨ Extraction complete!")
        print(f"\n📌 Next step: Use these config files with environment.py:")
        print(f"   python environment.py --org <org> --project <project> \\")
        print(f"     --json-folder \"{output_folder}\" --pat-file pat.txt --create-envs")
    except Exception as e:
        print(f"\n❌ Error during processing: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()