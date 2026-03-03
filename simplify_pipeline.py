import json
import os
import sys
import argparse
from pathlib import Path
from typing import Dict, Any, List
import datetime

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

def get_task_type(task_name: str) -> str:
    """Helper function to categorize task types based on name"""
    task_name_lower = task_name.lower()
    
    if "script" in task_name_lower or "powershell" in task_name_lower or "bash" in task_name_lower:
        return "Script"
    elif "azure cli" in task_name_lower or "az cli" in task_name_lower:
        return "Azure CLI"
    elif "iis" in task_name_lower or "web app" in task_name_lower or "web deploy" in task_name_lower:
        return "IIS Web App Deploy"
    elif "copy" in task_name_lower or "publish" in task_name_lower:
        return "Publish Artifact"
    elif "archive" in task_name_lower or "zip" in task_name_lower:
        return "Archive Files"
    elif "query" in task_name_lower and "work" in task_name_lower:
        return "Query Work Items"
    elif "azure monitor" in task_name_lower:
        return "Azure Monitor"
    elif "rest api" in task_name_lower or "invoke" in task_name_lower:
        return "Invoke REST API"
    else:
        return "Other"

def simplify_release_pipeline(input_data: Dict[str, Any], filename: str = "") -> Dict[str, Any]:
    """
    Parse a release pipeline JSON and create a simplified hierarchical structure
    following the exact organization specified.
    """
    
    # Create the main structure following the hierarchy
    simplified = {
        "Organization": {
            "Project": {
                "Pipelines": {
                    "Releases": {
                        "Release Definition": {
                            "name": input_data.get("name", ""),
                            "id": input_data.get("id", ""),
                            "path": input_data.get("path", ""),
                            "revision": input_data.get("revision", ""),
                            "release_name_format": input_data.get("releaseNameFormat", ""),
                            "created_by": safe_get(input_data, "createdBy", "displayName", default=""),
                            "created_on": input_data.get("createdOn", ""),
                            "modified_by": safe_get(input_data, "modifiedBy", "displayName", default=""),
                            "modified_on": input_data.get("modifiedOn", ""),
                            "Artifacts": [],
                            "Continuous Deployment Trigger": {
                                "enabled": False,
                                "type": "none",
                                "triggers": []
                            },
                            "Stages": []
                        }
                    }
                }
            }
        }
    }
    
    # Navigate to the Release Definition for easier access
    release_def = simplified["Organization"]["Project"]["Pipelines"]["Releases"]["Release Definition"]
    
    # Process Continuous Deployment Triggers
    triggers = input_data.get("triggers") or []
    if triggers:
        cd_triggers = []
        for trigger in triggers:
            if trigger.get("triggerType") == "artifactSource":
                cd_triggers.append({
                    "artifact_alias": safe_get(trigger, "artifactAlias", default=""),
                    "enabled": trigger.get("isEnabled", False)
                })
        
        if cd_triggers:
            release_def["Continuous Deployment Trigger"] = {
                "enabled": True,
                "type": "artifact_source",
                "triggers": cd_triggers
            }
    
    # Process Artifacts
    for artifact in input_data.get("artifacts") or []:
        try:
            # Get definition reference details
            def_ref = artifact.get("definitionReference") or {}
            definition = def_ref.get("definition") or {}
            project = def_ref.get("project") or {}
            
            artifact_info = {
                "name": artifact.get("alias", ""),
                "type": artifact.get("type", ""),
                "is_primary": artifact.get("isPrimary", False),
                "source": {
                    "project": project.get("name", ""),
                    "project_id": project.get("id", ""),
                    "definition_id": definition.get("id", ""),
                    "definition_name": definition.get("name", "")
                },
                "default_version": safe_get(def_ref, "defaultVersionType", "name", default="Latest")
            }
            release_def["Artifacts"].append(artifact_info)
        except Exception as e:
            print(f"      Warning: Error processing artifact: {str(e)}")
            continue
    
    # Process Environments (Stages)
    for env in input_data.get("environments") or []:
        try:
            stage_info = {
                "Stage": {
                    "name": env.get("name", ""),
                    "rank": env.get("rank", ""),
                    "owner": safe_get(env, "owner", "displayName", default=""),
                    "Pre-deployment conditions": {
                        "Pre-deployment approvals": [],
                        "Gates": None
                    },
                    "Jobs": [],
                    "Post-deployment conditions": {
                        "Post-deployment approvals": [],
                        "Gates": None
                    }
                }
            }
            
            stage = stage_info["Stage"]
            
            # Process Pre-deployment approvals
            pre_approvals = env.get("preDeployApprovals") or {}
            for approval in pre_approvals.get("approvals") or []:
                if not approval.get("isAutomated", True):
                    approver = approval.get("approver") or {}
                    approval_info = {
                        "approver": approver.get("displayName", ""),
                        "email": approver.get("uniqueName", ""),
                        "type": "manual",
                        "rank": approval.get("rank", "")
                    }
                    stage["Pre-deployment conditions"]["Pre-deployment approvals"].append(approval_info)
            
            # Process Pre-deployment Gates
            pre_gates = env.get("preDeploymentGates") or {}
            if pre_gates.get("gatesOptions") and pre_gates.get("gates"):
                gates_options = pre_gates["gatesOptions"]
                gates_info = {
                    "enabled": gates_options.get("isEnabled", False),
                    "timeout_minutes": gates_options.get("timeout", 0),
                    "sampling_interval": gates_options.get("samplingInterval", 0),
                    "stabilization_time": gates_options.get("stabilizationTime", 0),
                    "Gates": []
                }
                
                # Process individual gates
                for gate in pre_gates.get("gates") or []:
                    for task in gate.get("tasks") or []:
                        gate_task = {
                            "type": task.get("name", ""),
                            "task_id": task.get("taskId", ""),
                            "version": task.get("version", ""),
                            "enabled": task.get("enabled", False),
                            "inputs": task.get("inputs") or {}
                        }
                        gates_info["Gates"].append(gate_task)
                
                stage["Pre-deployment conditions"]["Gates"] = gates_info
            
            # Process Jobs and Tasks
            for phase in env.get("deployPhases") or []:
                job_info = {
                    "Job": {
                        "name": phase.get("name", ""),
                        "type": phase.get("phaseType", ""),
                        "condition": safe_get(phase, "deploymentInput", "condition", default="succeeded()"),
                        "agent": safe_get(phase, "deploymentInput", "agentSpecification", "identifier", default=""),
                        "Tasks": []
                    }
                }
                
                # Process tasks in this job
                for task in phase.get("workflowTasks") or []:
                    task_info = {
                        "name": task.get("name", ""),
                        "type": get_task_type(task.get("name", "")),
                        "task_id": task.get("taskId", ""),
                        "version": task.get("version", ""),
                        "enabled": task.get("enabled", True),
                        "condition": task.get("condition", "succeeded()"),
                        "inputs": task.get("inputs") or {}
                    }
                    job_info["Job"]["Tasks"].append(task_info)
                
                stage["Jobs"].append(job_info)
            
            # Process Post-deployment approvals
            post_approvals = env.get("postDeployApprovals") or {}
            for approval in post_approvals.get("approvals") or []:
                if not approval.get("isAutomated", True):
                    approver = approval.get("approver") or {}
                    approval_info = {
                        "approver": approver.get("displayName", ""),
                        "email": approver.get("uniqueName", ""),
                        "type": "manual",
                        "rank": approval.get("rank", "")
                    }
                    stage["Post-deployment conditions"]["Post-deployment approvals"].append(approval_info)
            
            # Process Post-deployment Gates
            post_gates = env.get("postDeploymentGates") or {}
            if post_gates.get("gatesOptions") and post_gates.get("gates"):
                gates_options = post_gates["gatesOptions"]
                gates_info = {
                    "enabled": gates_options.get("isEnabled", False),
                    "timeout_minutes": gates_options.get("timeout", 0),
                    "sampling_interval": gates_options.get("samplingInterval", 0),
                    "stabilization_time": gates_options.get("stabilizationTime", 0),
                    "Gates": []
                }
                
                # Process individual gates
                for gate in post_gates.get("gates") or []:
                    for task in gate.get("tasks") or []:
                        gate_task = {
                            "type": task.get("name", ""),
                            "task_id": task.get("taskId", ""),
                            "version": task.get("version", ""),
                            "enabled": task.get("enabled", False),
                            "inputs": task.get("inputs") or {}
                        }
                        gates_info["Gates"].append(gate_task)
                
                stage["Post-deployment conditions"]["Gates"] = gates_info
            
            release_def["Stages"].append(stage_info)
            
        except Exception as e:
            print(f"      Warning: Error processing stage {env.get('name', 'unknown')}: {str(e)}")
            continue
    
    return simplified

def process_folder(input_folder: str, output_base_folder: str = "output"):
    """
    Process all JSON files in a folder and create simplified versions.
    """
    
    # Convert to absolute path for better display
    input_folder = os.path.abspath(input_folder)
    
    # Create output folder path
    output_folder = os.path.join(output_base_folder, "simplified_json")
    output_folder = os.path.abspath(output_folder)
    
    # Create output directory if it doesn't exist
    Path(output_folder).mkdir(parents=True, exist_ok=True)
    
    # Get all JSON files in the input folder
    json_files = list(Path(input_folder).glob("*.json"))
    
    if not json_files:
        print(f"\n❌ No JSON files found in: {input_folder}")
        print("Please make sure the folder contains .json files.")
        return
    
    print(f"\n✅ Found {len(json_files)} JSON file(s) to process")
    print(f"📂 Input folder: {input_folder}")
    print(f"📂 Output folder: {output_folder}\n")
    
    processed_files = 0
    failed_files = 0
    failed_list = []
    
    for json_file in json_files:
        try:
            print(f"🔄 Processing: {json_file.name}...", end=" ", flush=True)
            
            # Read the input JSON file
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Simplify the pipeline
            simplified = simplify_release_pipeline(data, json_file.name)
            
            # Create output filename (same name but with _simplified suffix)
            output_filename = json_file.stem + "_simplified.json"
            output_path = os.path.join(output_folder, output_filename)
            
            # Save the simplified JSON
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(simplified, f, indent=2)
            
            print("✅")
            processed_files += 1
            
        except json.JSONDecodeError as e:
            print("❌")
            print(f"     Error: Invalid JSON format - {str(e)}")
            failed_files += 1
            failed_list.append(f"{json_file.name} (Invalid JSON: {str(e)})")
        except Exception as e:
            print("❌")
            print(f"     Error: {str(e)}")
            failed_files += 1
            failed_list.append(f"{json_file.name} ({str(e)})")
    
    # Print summary
    print("\n" + "="*60)
    print("📊 PROCESSING SUMMARY")
    print("="*60)
    print(f"📍 Input folder: {input_folder}")
    print(f"📍 Output folder: {output_folder}")
    print(f"📄 Total files found: {len(json_files)}")
    print(f"✅ Successfully processed: {processed_files}")
    print(f"❌ Failed: {failed_files}")
    
    if failed_list:
        print("\nFailed files:")
        for failed in failed_list:
            print(f"  • {failed}")
    
    # Create a summary file
    summary = {
        "processing_date": datetime.datetime.now().isoformat(),
        "input_folder": input_folder,
        "output_folder": output_folder,
        "total_files": len(json_files),
        "processed_files": processed_files,
        "failed_files": failed_files,
        "failed_files_details": failed_list,
        "files_processed": [f.name for f in json_files if (Path(output_folder) / (f.stem + "_simplified.json")).exists()]
    }
    
    summary_path = os.path.join(output_folder, "processing_summary.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    
    print(f"\n📋 Summary file created: {summary_path}")
    print("="*60)

def main():
    """Main function with command line arguments."""
    parser = argparse.ArgumentParser(
        description='Simplify Azure DevOps release pipeline JSON files',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s C:\\Users\\John\\Documents\\json_files
  %(prog)s /home/user/documents/json_files -o custom_output
  %(prog)s "C:\\My Pipelines\\json files" --output "C:\\My Output"
        """
    )
    
    parser.add_argument(
        'input_folder',
        help='Path to folder containing JSON files (use quotes if path has spaces)'
    )
    
    parser.add_argument(
        '-o', '--output',
        default='output',
        help='Output folder name (default: output)'
    )
    
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Show verbose output'
    )
    
    args = parser.parse_args()
    
    # Print banner
    print("\n" + "="*60)
    print("🚀 Azure DevOps Release Pipeline JSON Simplifier")
    print("="*60)
    
    # Check if input folder exists
    if not os.path.exists(args.input_folder):
        print(f"\n❌ Error: Input folder does not exist: {args.input_folder}")
        print("\nPlease provide a valid folder path.")
        print("Usage: python script.py <input_folder> [-o output_folder]")
        print("Example: python script.py C:\\Users\\John\\Documents\\json_files")
        sys.exit(1)
    
    # Check if it's a directory
    if not os.path.isdir(args.input_folder):
        print(f"\n❌ Error: Path is not a directory: {args.input_folder}")
        print("Please provide a folder path, not a file.")
        sys.exit(1)
    
    # Process the folder
    try:
        process_folder(args.input_folder, args.output)
        print("\n✨ Processing complete!")
    except Exception as e:
        print(f"\n❌ Error during processing: {str(e)}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()