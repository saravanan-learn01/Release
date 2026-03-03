import requests
from requests.auth import HTTPBasicAuth
import json
import os
from datetime import datetime
import logging
import argparse

# Global variable for maximum project count
max_project_count = 10

def get_arguments():
    parser = argparse.ArgumentParser(description="Collect release pipeline information from Azure DevOps Server 2019")
    parser.add_argument('--server_host_name', required=True, help="The URL host name (e.g., dev.azure.com)")
    parser.add_argument('--collection_name', required=True, help="The Collection/Organization name")
    parser.add_argument('--pat_token_file', required=True, help="The absolute path to the file containing the PAT token")
    parser.add_argument('--project_file', required=True, help="The absolute path to the file containing the project names")
    parser.add_argument('--api_version', default="7.0", help="Azure DevOps API version (default: 7.0)")
    parser.add_argument('--protocol', default="https", choices=['http', 'https'], help="Protocol to use (default: https)")
    return parser.parse_args()

def read_pat_token(file_path):
    try:
        with open(file_path, 'r') as file:
            pat_token = file.read().strip()
        return pat_token
    except Exception as e:
        logging.error(f"Failed to read PAT token from file: {e}")
        return None

def read_project_file(file_path):
    try:
        with open(file_path, 'r') as file:
            projects = [line.strip() for line in file.readlines()]
        return projects
    except Exception as e:
        logging.error(f"Failed to read project file: {e}")
        return []

def get_projects(session, protocol, instance, collection_name, pat_token, api_version):
    url = f"{protocol}://{instance}/{collection_name}/_apis/projects?api-version={api_version}"
    headers = {'Content-Type': 'application/json'}
    try:
        response = session.get(url, headers=headers, auth=HTTPBasicAuth('', pat_token))
        response.raise_for_status()
        if response.status_code == 200:
            return response.json()["value"]
        else:
            print(f"Failed to fetch projects: {response.status_code} - {response.text}")
            return []
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err} - URL: {url}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get projects: {e}")
        return []

def get_release_definitions(session, protocol, instance, collection_name, project_name, pat_token, api_version):
    """
    Fetch all release definitions for a project using the Release Management API
    URL format: https://vsrm.dev.azure.com/{organization}/{project}/_apis/release/definitions?api-version={api_version}
    """
    # Construct URL based on whether it's cloud or on-premises
    if "dev.azure.com" in instance or "visualstudio.com" in instance:
        # Cloud service URL pattern (using vsrm subdomain)
        url = f"{protocol}://vsrm.{instance}/{collection_name}/{project_name}/_apis/release/definitions?api-version={api_version}"
    else:
        # On-premises TFS/Azure DevOps Server URL pattern
        url = f"{protocol}://{instance}/tfs/{collection_name}/{project_name}/_apis/release/definitions?api-version={api_version}"
    
    headers = {'Content-Type': 'application/json'}
    try:
        response = session.get(url, headers=headers, auth=HTTPBasicAuth('', pat_token))
        response.raise_for_status()
        if response.status_code == 200:
            return response.json()["value"]
        else:
            print(f"Failed to fetch release definitions for project {project_name}: {response.status_code} - {response.text}")
            return []
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err} - URL: {url}")
        return []
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get release definitions for project {project_name}: {e}")
        return []

def get_release_definition_details(session, protocol, instance, collection_name, project_name, definition_id, pat_token, api_version):
    """
    Fetch detailed information for a specific release definition
    URL format: https://vsrm.dev.azure.com/{organization}/{project}/_apis/release/definitions/{definitionId}?api-version={api_version}
    """
    if "dev.azure.com" in instance or "visualstudio.com" in instance:
        # Cloud service URL pattern
        url = f"{protocol}://vsrm.{instance}/{collection_name}/{project_name}/_apis/release/definitions/{definition_id}?api-version={api_version}"
    else:
        # On-premises TFS/Azure DevOps Server URL pattern
        url = f"{protocol}://{instance}/tfs/{collection_name}/{project_name}/_apis/release/definitions/{definition_id}?api-version={api_version}"
    
    headers = {'Content-Type': 'application/json'}
    try:
        response = session.get(url, headers=headers, auth=HTTPBasicAuth('', pat_token))
        response.raise_for_status()
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Failed to fetch release definition details for ID {definition_id}: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.HTTPError as http_err:
        logging.error(f"HTTP error occurred: {http_err} - URL: {url}")
        return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Failed to get release definition details for ID {definition_id}: {e}")
        return None

def ensure_directories_exist():
    logs_dir = os.path.join(os.getcwd(), "Logs")
    output_dir = os.path.join(os.getcwd(), "Output")

    if not os.path.exists(logs_dir):
        os.makedirs(logs_dir)
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    return logs_dir, output_dir

def save_to_files(collection_name, project_name, pipeline_name, pipeline_id, data, output_dir):
    """
    Save release pipeline data to JSON files
    """
    # Create project-specific directory for release definitions
    project_dir = os.path.join(output_dir, collection_name, project_name, "release_definitions")
    os.makedirs(project_dir, exist_ok=True)
    
    # Clean pipeline name to make it filesystem-friendly
    # Remove invalid characters and replace with underscores
    clean_pipeline_name = "".join(c for c in pipeline_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    clean_pipeline_name = clean_pipeline_name.replace(' ', '_')
    
    # Create filename in the same format as original script: collection_project_pipeline_name_id.json
    file_name = f"{collection_name}_{project_name}_{clean_pipeline_name}_{pipeline_id}.json"
    file_path = os.path.join(project_dir, file_name)
    
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
    
    print(f"  Saved release pipeline: {pipeline_name} (ID: {pipeline_id})")

def main():
    args = get_arguments()
    instance = args.server_host_name
    collection_name = args.collection_name
    pat_token_file = args.pat_token_file
    project_file = args.project_file
    api_version = args.api_version
    protocol = args.protocol
    script_name = os.path.basename(__file__).replace('.py', '')

    # Ensure required directories exist
    logs_dir, output_dir = ensure_directories_exist()

    # Setup logging
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = os.path.join(logs_dir, f"{script_name}_{collection_name}_{timestamp}_exception_log.log")
    logging.basicConfig(filename=log_filename, level=logging.ERROR,
                        format='%(asctime)s %(levelname)s %(message)s')

    # Read PAT token
    pat_token = read_pat_token(pat_token_file)
    if not pat_token:
        print("Failed to read PAT token. Exiting.")
        return

    # Read project names from file
    project_names = read_project_file(project_file)
    if not project_names:
        print("Failed to read project names. Exiting.")
        return

    # Check project count against max_project_count
    if len(project_names) > max_project_count:
        print(f"Number of projects mentioned in the file ({len(project_names)}) is greater than threshold value {max_project_count}")
        return

    # Load existing log file if present (for tracking processed projects)
    log_file_path = os.path.join(logs_dir, f"{script_name}_{collection_name}_data_collection_status.txt")
    collected_projects = []
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r') as log_file:
            collected_projects = [line.strip() for line in log_file.readlines()]

    print(f"\n{'='*60}")
    print(f"Starting Release Pipeline Discovery")
    print(f"Instance: {instance}")
    print(f"Collection/Organization: {collection_name}")
    print(f"API Version: {api_version}")
    print(f"Projects to process: {len(project_names)}")
    print(f"{'='*60}\n")

    # Create a session for connection pooling
    with requests.Session() as session:
        # Fetch the list of projects from Azure DevOps
        print("Fetching project metadata...")
        projects = get_projects(session, protocol, instance, collection_name, pat_token, api_version)
        project_metadata = {project['name']: project for project in projects}
        print(f"Found {len(projects)} projects in the collection\n")

        # Loop over each project name from the file
        for project_name in project_names:
            if project_name in collected_projects:
                print(f"Project '{project_name}' already processed. Skipping...")
                continue

            if project_name in project_metadata:
                print(f"\n{'─'*50}")
                print(f"Processing project: {project_name}")
                print(f"{'─'*50}")
                
                # Fetch release definitions for the project
                release_definitions = get_release_definitions(session, protocol, instance, collection_name, project_name, pat_token, api_version)
                
                if release_definitions:
                    print(f"  Found {len(release_definitions)} release pipeline(s)")
                    
                    for release_definition in release_definitions:
                        definition_id = release_definition['id']
                        pipeline_name = release_definition['name']
                        
                        # Fetch detailed release definition
                        definition_details = get_release_definition_details(session, protocol, instance, collection_name, project_name, definition_id, pat_token, api_version)
                        
                        if definition_details:
                            save_to_files(collection_name, project_name, pipeline_name, definition_id, definition_details, output_dir)
                        else:
                            print(f"  Failed to fetch details for release pipeline: {pipeline_name} (ID: {definition_id})")
                else:
                    print(f"  No release pipelines found in project '{project_name}'")

                # Log the project name as processed
                with open(log_file_path, 'a') as log_file:
                    log_file.write(f"{project_name}\n")
                
                print(f"  Project '{project_name}' processing complete")

            else:
                print(f"\nProject '{project_name}' not found in the collection metadata.")
                logging.error(f"Project {project_name} is not present in the metadata.")

    print(f"\n{'='*60}")
    print(f"Script execution completed!")
    print(f"Output directory: {output_dir}")
    print(f"Logs directory: {logs_dir}")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()