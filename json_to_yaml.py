#!/usr/bin/env python3
"""
Azure DevOps Release Pipeline JSON to YAML Converter
This script reads JSON release definition files and converts them to YAML pipeline format.
It searches for an 'Output' folder (case-sensitive) and generates YAML files inside 'yaml_output' folder.
"""

import os
import json
import sys
import argparse
from pathlib import Path
import re

def sanitize_stage_name(name):
    """Convert environment name to valid YAML stage name"""
    # Replace special characters with underscores
    sanitized = re.sub(r'[^a-zA-Z0-9]', '_', name)
    # Ensure it doesn't start with a number
    if sanitized and sanitized[0].isdigit():
        sanitized = f"stage_{sanitized}"
    return sanitized.upper()

def get_pool_config(environment):
    """Extract pool configuration from environment"""
    pool_config = {}
    
    if 'deployPhases' in environment and environment['deployPhases']:
        deploy_phase = environment['deployPhases'][0]
        if 'deploymentInput' in deploy_phase:
            deployment_input = deploy_phase['deploymentInput']
            
            # Check for agent specification
            if deployment_input.get('agentSpecification'):
                if deployment_input['agentSpecification'].get('identifier'):
                    pool_config['vmImage'] = deployment_input['agentSpecification']['identifier']
            
            # Check for queueId (agent pool)
            if deployment_input.get('queueId'):
                # You might want to map queueId to actual pool names
                # This is a simplified mapping - adjust based on your environment
                queue_map = {
                    4: 'Default',
                    9: 'windows-latest',
                    1: 'Azure Pipelines'
                }
                queue_id = deployment_input['queueId']
                if queue_id in queue_map:
                    if queue_id == 9:  # This is vmImage
                        pool_config['vmImage'] = queue_map[queue_id]
                    else:
                        pool_config['name'] = queue_map[queue_id]
    
    return pool_config

def get_condition(environment, all_env_names):
    """Extract condition for the environment"""
    if 'conditions' in environment and environment['conditions']:
        condition = environment['conditions'][0]
        if condition.get('conditionType') == 'environmentState':
            # Depends on another environment
            dep_name = condition.get('name', '')
            if dep_name in all_env_names:
                # Check if it's a failure condition from deploymentInput
                if 'deployPhases' in environment and environment['deployPhases']:
                    deploy_phase = environment['deployPhases'][0]
                    if 'deploymentInput' in deploy_phase:
                        phase_condition = deploy_phase['deploymentInput'].get('condition', 'succeeded()')
                        if phase_condition == 'failed()':
                            return f"failed('{sanitize_stage_name(dep_name)}')"
                return f"succeeded('{sanitize_stage_name(dep_name)}')"
        elif condition.get('conditionType') == 'event':
            return 'succeeded()'
    
    return 'succeeded()'

def get_dependencies(environment, all_env_names, rank):
    """Determine dependencies based on rank and conditions"""
    dependencies = []
    
    if 'conditions' in environment and environment['conditions']:
        for condition in environment['conditions']:
            if condition.get('conditionType') == 'environmentState':
                dep_name = condition.get('name', '')
                if dep_name in all_env_names:
                    dependencies.append(sanitize_stage_name(dep_name))
    
    # If no explicit dependencies but rank > 1, depend on previous environment
    if not dependencies and rank > 1:
        # Find environment with rank = current rank - 1
        pass  # This will be handled in the main generation logic
    
    return dependencies

def convert_task_to_yaml(task):
    """Convert a workflow task to YAML format"""
    task_yaml = []
    
    # Get task details
    task_name = task.get('name', 'Unknown Task')
    task_id = task.get('taskId', '')
    version = task.get('version', '1.*')
    
    # Map taskId to known task names (you may need to expand this mapping)
    task_mapping = {
        '1d341bb0-2106-458c-8422-d00bcea6512a': 'CopyPublishArtifact@1',
        '2ff763a7-ce83-4e1f-bc89-0ae63477cebe': 'PublishBuildArtifacts@1',
        'd8b84976-e99a-4b86-b885-4849694435b0': 'ArchiveFiles@2',
        '3a6a2d63-f2b2-4e93-bcf9-0cbe22f5dc26': 'Ant@1',
        '5541a522-603c-47ad-91fc-a4b1d163081b': 'DotNetCoreCLI@2',
        '521d1e15-f5fb-4b73-a93b-b2fe88a9a286': 'Grunt@0',
        '8413c881-4959-43d5-8840-b4ea0ffc5cfd': 'KubectlInstaller@0',
        'f5fd8599-ccfa-4d6e-b965-4d14bed7097b': 'NuGetAuthenticate@1',
        'b7e8b412-0437-4065-9371-edc5881de25b': 'DeleteFiles@1',
        '8d8eebd8-2b94-4c97-85af-839254cc6da4': 'Gradle@4',
        'd9bafed4-0b18-4f58-968d-86655b4d2ce9': 'CmdLine@2',
        'ac4ee482-65da-4485-a532-7b085873e532': 'Maven@4',
        '33c63b11-352b-45a2-ba1b-54cb568a29ca': 'UsePythonVersion@0',
        'bcb64569-d51a-4af0-9c01-ea5d05b3b622': 'ManualIntervention@8',
        'e213ff0f-5d5c-4791-802d-52ea3e7be1f1': 'PowerShell@2',
    }
    
    task_ref = task_mapping.get(task_id, f'Task@{version.split(".")[0]}')
    
    task_yaml.append(f"            - task: {task_ref}")
    task_yaml.append(f"              displayName: '{task_name}'")
    
    # Add inputs
    if 'inputs' in task and task['inputs']:
        task_yaml.append(f"              inputs:")
        for key, value in task['inputs'].items():
            # Format value based on type
            if isinstance(value, bool):
                formatted_value = str(value).lower()
            elif isinstance(value, (int, float)):
                formatted_value = str(value)
            else:
                formatted_value = f"'{value}'" if value else "''"
            
            # Handle multiline strings (like scripts)
            if key == 'script' and value and '\n' in value:
                task_yaml.append(f"                {key}: |")
                for line in value.split('\n'):
                    task_yaml.append(f"                  {line}")
            else:
                task_yaml.append(f"                {key}: {formatted_value}")
    
    return task_yaml

def generate_yaml_from_json(json_data, filename):
    """Generate YAML pipeline from JSON data"""
    yaml_lines = []
    
    # Get pipeline name from JSON or filename
    pipeline_name = json_data.get('name', filename.stem)
    
    # Header
    yaml_lines.append("# Azure DevOps Pipeline YAML Structure")
    yaml_lines.append(f"# Generated from: {filename.name}")
    yaml_lines.append(f"name: $(Date:yyyyMMdd).$(Rev:r)")
    yaml_lines.append("")
    yaml_lines.append("trigger: none")
    yaml_lines.append("")
    
    # Resources
    yaml_lines.append("resources:")
    yaml_lines.append("  pipelines:")
    
    # Get primary artifact
    primary_artifact = None
    if 'artifacts' in json_data and json_data['artifacts']:
        for artifact in json_data['artifacts']:
            if artifact.get('isPrimary', False):
                primary_artifact = artifact
                break
        if not primary_artifact and json_data['artifacts']:
            primary_artifact = json_data['artifacts'][0]
    
    if primary_artifact:
        alias = primary_artifact.get('alias', 'artifact')
        source = "unknown"
        if 'definitionReference' in primary_artifact:
            def_ref = primary_artifact['definitionReference']
            if 'definition' in def_ref:
                source = def_ref['definition'].get('name', 'unknown')
        
        yaml_lines.append(f"    - pipeline: {alias}")
        yaml_lines.append(f"      source: {source}")
        yaml_lines.append(f"      trigger: none")
    else:
        yaml_lines.append("    # No artifacts found")
    
    yaml_lines.append("")
    yaml_lines.append("stages:")
    
    # Sort environments by rank
    environments = sorted(json_data.get('environments', []), key=lambda x: x.get('rank', 999))
    env_names = [env.get('name', 'Unknown') for env in environments]
    
    # Generate stages for each environment
    for i, env in enumerate(environments):
        env_name = env.get('name', f'Stage_{i+1}')
        stage_name = sanitize_stage_name(env_name)
        
        yaml_lines.append(f"  # {env_name} Environment")
        yaml_lines.append(f"  - stage: {stage_name}")
        yaml_lines.append(f"    displayName: '{env_name}'")
        
        # Add dependsOn
        if i > 0:
            prev_stage = sanitize_stage_name(environments[i-1].get('name', f'Stage_{i}'))
            yaml_lines.append(f"    dependsOn: {prev_stage}")
        
        # Add condition
        condition = get_condition(env, env_names)
        yaml_lines.append(f"    condition: {condition}")
        
        yaml_lines.append(f"    jobs:")
        
        # Deployment job
        yaml_lines.append(f"    - deployment: Deploy_{stage_name}")
        yaml_lines.append(f"      displayName: 'Deploy to {env_name}'")
        
        # Pool configuration
        pool_config = get_pool_config(env)
        if pool_config:
            yaml_lines.append(f"      pool:")
            if 'vmImage' in pool_config:
                yaml_lines.append(f"        vmImage: '{pool_config['vmImage']}'")
            if 'name' in pool_config:
                yaml_lines.append(f"        name: '{pool_config['name']}'")
        else:
            yaml_lines.append(f"      pool:")
            yaml_lines.append(f"        vmImage: 'windows-latest'  # Default pool")
        
        yaml_lines.append(f"      environment: '{env_name}'")
        yaml_lines.append(f"      strategy:")
        yaml_lines.append(f"        runOnce:")
        yaml_lines.append(f"          deploy:")
        yaml_lines.append(f"            steps:")
        
        # Add workflow tasks
        tasks_added = False
        if 'deployPhases' in env and env['deployPhases']:
            for phase in env['deployPhases']:
                if 'workflowTasks' in phase and phase['workflowTasks']:
                    for task in phase['workflowTasks']:
                        if task.get('enabled', True):  # Only add enabled tasks
                            task_yaml = convert_task_to_yaml(task)
                            yaml_lines.extend(task_yaml)
                            yaml_lines.append("")
                            tasks_added = True
        
        if not tasks_added:
            yaml_lines.append(f"            # No workflow tasks defined for this environment")
            yaml_lines.append(f"            - script: echo 'No tasks defined for {env_name}'")
            yaml_lines.append("")
    
    return "\n".join(yaml_lines)

def find_output_folder(start_path):
    """Search for 'Output' folder (case-sensitive) starting from start_path"""
    start_path = Path(start_path).resolve()
    
    # First check if start_path itself is the Output folder
    if start_path.name == "Output" and start_path.is_dir():
        return start_path
    
    # Search in the current directory and parent directories
    current = start_path
    while current != current.parent:
        output_candidate = current / "Output"
        if output_candidate.is_dir():
            return output_candidate
        current = current.parent
    
    # If not found, search recursively in subdirectories (limited depth)
    for root, dirs, files in os.walk(start_path):
        if "Output" in dirs:
            return Path(root) / "Output"
    
    return None

def process_json_file(json_path, output_dir):
    """Process a single JSON file and generate YAML"""
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            json_data = json.load(f)
        
        # Generate YAML content
        yaml_content = generate_yaml_from_json(json_data, json_path)
        
        # Create output filename
        base_name = json_path.stem
        yaml_filename = f"{base_name}.yml"
        yaml_path = output_dir / yaml_filename
        
        # Write YAML file
        with open(yaml_path, 'w', encoding='utf-8') as f:
            f.write(yaml_content)
        
        print(f"✓ Generated: {yaml_filename}")
        return True
        
    except json.JSONDecodeError as e:
        print(f"✗ Error parsing JSON in {json_path.name}: {e}")
        return False
    except Exception as e:
        print(f"✗ Error processing {json_path.name}: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(
        description='Convert Azure DevOps release pipeline JSON files to YAML format'
    )
    parser.add_argument(
        'input_folder',
        help='Path to folder containing JSON files'
    )
    
    args = parser.parse_args()
    
    # Check if input folder exists
    input_path = Path(args.input_folder)
    if not input_path.exists() or not input_path.is_dir():
        print(f"Error: Input folder '{args.input_folder}' does not exist or is not a directory")
        sys.exit(1)
    
    # Search for 'Output' folder (case-sensitive)
    print(f"Searching for 'Output' folder (case-sensitive)...")
    output_base = find_output_folder(input_path)
    
    if not output_base:
        print(f"Error: Could not find 'Output' folder. Please ensure there is a folder named exactly 'Output' (case-sensitive) in the path.")
        print(f"Searched from: {input_path}")
        sys.exit(1)
    
    print(f"Found Output folder: {output_base}")
    
    # Create yaml_output folder inside Output folder
    output_path = output_base / "yaml_output"
    output_path.mkdir(parents=True, exist_ok=True)
    
    print(f"Input folder: {input_path}")
    print(f"Output folder: {output_path}")
    print("-" * 50)
    
    # Find all JSON files
    json_files = list(input_path.glob("*.json"))
    
    if not json_files:
        print(f"No JSON files found in {input_path}")
        sys.exit(0)
    
    print(f"Found {len(json_files)} JSON file(s)")
    print("-" * 50)
    
    # Process each JSON file
    successful = 0
    for json_file in json_files:
        if process_json_file(json_file, output_path):
            successful += 1
    
    print("-" * 50)
    print(f"Successfully generated {successful}/{len(json_files)} YAML files")
    print(f"YAML files saved to: {output_path}")

if __name__ == "__main__":
    main()