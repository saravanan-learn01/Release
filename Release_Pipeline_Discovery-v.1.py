import requests
from requests.auth import HTTPBasicAuth
import json
import os
from datetime import datetime
import logging
import argparse
import time
import csv

# Global variables
max_project_count = 10
RATE_LIMIT_DELAY = 5  # 5 seconds delay between API calls
API_VERSION = "7.0"    # Hardcoded API version
PROTOCOL = "https"     # Hardcoded protocol

def get_arguments():
    parser = argparse.ArgumentParser(description="Collect release pipeline information from Azure DevOps Server 2019")
    parser.add_argument('--server_host_name', required=True, help="The URL host name (e.g., dev.azure.com)")
    parser.add_argument('--pat_token_file', required=True, help="The absolute path to the file containing the PAT token")
    parser.add_argument('--project_name', required=True, help="The absolute path to the CSV file containing collection and project names")
    return parser.parse_args()

def read_pat_token(file_path):
    try:
        with open(file_path, 'r') as file:
            pat_token = file.read().strip()
        return pat_token
    except Exception as e:
        logging.error(f"Failed to read PAT token from file: {e}")
        return None

def read_projects_from_csv(file_path):
    """
    Read collection_name and project_name from CSV file
    CSV format: Column A = collection_name, Column B = project_name
    """
    projects_data = []
    try:
        with open(file_path, 'r') as csvfile:
            csv_reader = csv.reader(csvfile)
            for row in csv_reader:
                if len(row) >= 2:  # Ensure row has at least 2 columns
                    collection_name = row[0].strip()
                    project_name = row[1].strip()
                    if collection_name and project_name:  # Skip empty entries
                        projects_data.append({
                            'collection_name': collection_name,
                            'project_name': project_name
                        })
        
        # Group projects by collection
        projects_by_collection = {}
        for item in projects_data:
            collection = item['collection_name']
            if collection not in projects_by_collection:
                projects_by_collection[collection] = []
            projects_by_collection[collection].append(item['project_name'])
        
        return projects_by_collection
    except Exception as e:
        logging.error(f"Failed to read projects CSV file: {e}")
        return {}

def get_projects(session, instance, collection_name, pat_token):
    """Fetch all projects for a collection to validate project existence"""
    url = f"{PROTOCOL}://{instance}/{collection_name}/_apis/projects?api-version={API_VERSION}"
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

def get_release_definitions(session, instance, collection_name, project_name, pat_token):
    """
    Fetch all release definitions for a project using the Release Management API
    """
    # Construct URL based on whether it's cloud or on-premises
    if "dev.azure.com" in instance or "visualstudio.com" in instance:
        # Cloud service URL pattern (using vsrm subdomain)
        url = f"{PROTOCOL}://vsrm.{instance}/{collection_name}/{project_name}/_apis/release/definitions?api-version={API_VERSION}"
    else:
        # On-premises TFS/Azure DevOps Server URL pattern
        url = f"{PROTOCOL}://{instance}/tfs/{collection_name}/{project_name}/_apis/release/definitions?api-version={API_VERSION}"
    
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

def get_release_definition_details(session, instance, collection_name, project_name, definition_id, pat_token):
    """
    Fetch detailed information for a specific release definition
    """
    if "dev.azure.com" in instance or "visualstudio.com" in instance:
        # Cloud service URL pattern
        url = f"{PROTOCOL}://vsrm.{instance}/{collection_name}/{project_name}/_apis/release/definitions/{definition_id}?api-version={API_VERSION}"
    else:
        # On-premises TFS/Azure DevOps Server URL pattern
        url = f"{PROTOCOL}://{instance}/tfs/{collection_name}/{project_name}/_apis/release/definitions/{definition_id}?api-version={API_VERSION}"
    
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
    Save release pipeline data to JSON files in collection_name/project_name structure
    """
    # Create collection and project-specific directory structure
    project_dir = os.path.join(output_dir, collection_name, project_name)
    os.makedirs(project_dir, exist_ok=True)
    
    # Clean pipeline name to make it filesystem-friendly
    clean_pipeline_name = "".join(c for c in pipeline_name if c.isalnum() or c in (' ', '-', '_')).rstrip()
    clean_pipeline_name = clean_pipeline_name.replace(' ', '_')
    
    # Create filename with collection_project_pipeline_name_id format
    file_name = f"{collection_name}_{project_name}_{clean_pipeline_name}_{pipeline_id}.json"
    file_path = os.path.join(project_dir, file_name)
    
    with open(file_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
    
    print(f"  Saved release pipeline: {pipeline_name} (ID: {pipeline_id})")
    return file_path

def setup_logging():
    """Setup logging with detailed formatting"""
    logs_dir, _ = ensure_directories_exist()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Detailed log file
    log_filename = os.path.join(logs_dir, f"Release_Pipeline_Discovery_{timestamp}_detailed.log")
    
    # Configure logging with detailed format
    logging.basicConfig(
        filename=log_filename,
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Add console handler for INFO level
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('').addHandler(console)
    
    return logs_dir, log_filename

def main():
    args = get_arguments()
    instance = args.server_host_name
    pat_token_file = args.pat_token_file
    project_file = args.project_name  # This is the path to the CSV file
    
    # Hardcoded values
    api_version = API_VERSION
    protocol = PROTOCOL
    rate_limit_delay = RATE_LIMIT_DELAY
    
    # Ensure required directories exist and get both paths
    logs_dir, output_dir = ensure_directories_exist()
    
    # Setup logging
    log_filename = os.path.join(logs_dir, f"Release_Pipeline_Discovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}_detailed.log")
    
    # Configure logging with detailed format
    logging.basicConfig(
        filename=log_filename,
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-8s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Add console handler for INFO level
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    console.setFormatter(logging.Formatter('%(message)s'))
    logging.getLogger('').addHandler(console)
    
    script_name = os.path.basename(__file__).replace('.py', '')
    
    # Log script start with parameters
    logging.info("=" * 80)
    logging.info("SCRIPT STARTED")
    logging.info("=" * 80)
    logging.info(f"Script: {__file__}")
    logging.info(f"Instance: {instance}")
    logging.info(f"API Version: {api_version} (hardcoded)")
    logging.info(f"Protocol: {protocol} (hardcoded)")
    logging.info(f"Rate Limit Delay: {rate_limit_delay} seconds (hardcoded)")
    logging.info(f"Project CSV File: {project_file}")
    logging.info(f"PAT Token File: {pat_token_file}")
    logging.info(f"Log File: {log_filename}")
    logging.info(f"Output Directory: {output_dir}")
    logging.info("=" * 80)

    # Read PAT token
    pat_token = read_pat_token(pat_token_file)
    if not pat_token:
        logging.error("Failed to read PAT token. Exiting.")
        print("Failed to read PAT token. Exiting.")
        return

    # Read projects from CSV file
    projects_by_collection = read_projects_from_csv(project_file)
    if not projects_by_collection:
        logging.error("Failed to read project data from CSV file. Exiting.")
        print("Failed to read project data from CSV file. Exiting.")
        return

    # Calculate total projects
    total_projects = sum(len(projects) for projects in projects_by_collection.values())
    
    # Check project count against max_project_count
    if total_projects > max_project_count:
        logging.error(f"Total number of projects ({total_projects}) is greater than threshold value {max_project_count}")
        print(f"Total number of projects ({total_projects}) is greater than threshold value {max_project_count}")
        return

    print(f"\n{'='*60}")
    print(f"Starting Release Pipeline Discovery")
    print(f"Instance: {instance}")
    print(f"API Version: {api_version} (hardcoded)")
    print(f"Protocol: {protocol} (hardcoded)")
    print(f"Rate Limit Delay: {rate_limit_delay} seconds (hardcoded)")
    print(f"Collections to process: {len(projects_by_collection)}")
    print(f"Total projects to process: {total_projects}")
    print(f"Project CSV File: {project_file}")
    print(f"{'='*60}\n")

    # Load existing log file if present (for tracking processed projects)
    log_file_path = os.path.join(logs_dir, f"{script_name}_data_collection_status.txt")
    processed_entries = []
    if os.path.exists(log_file_path):
        with open(log_file_path, 'r') as log_file:
            processed_entries = [line.strip() for line in log_file.readlines()]

    # Create a session for connection pooling
    with requests.Session() as session:
        # Process each collection and its projects
        for collection_name, project_names in projects_by_collection.items():
            print(f"\n{'#'*60}")
            print(f"Processing Collection: {collection_name}")
            print(f"Projects in collection: {len(project_names)}")
            print(f"{'#'*60}")
            
            logging.info(f"Starting processing for collection: {collection_name}")
            
            # Fetch the list of projects from Azure DevOps for this collection
            print(f"\nFetching project metadata for collection '{collection_name}'...")
            projects = get_projects(session, instance, collection_name, pat_token)
            project_metadata = {project['name']: project for project in projects}
            print(f"Found {len(projects)} projects in the collection\n")
            
            # Apply rate limiting
            time.sleep(rate_limit_delay)

            # Loop over each project name for this collection
            for project_name in project_names:
                # Create unique identifier for project-collection combination
                project_entry = f"{collection_name}|{project_name}"
                
                if project_entry in processed_entries:
                    print(f"Project '{project_name}' in collection '{collection_name}' already processed. Skipping...")
                    logging.info(f"Skipping already processed project: {collection_name}/{project_name}")
                    continue

                if project_name in project_metadata:
                    print(f"\n{'─'*50}")
                    print(f"Processing project: {project_name} (Collection: {collection_name})")
                    print(f"{'─'*50}")
                    
                    logging.info(f"Starting processing for project: {collection_name}/{project_name}")
                    
                    # Fetch release definitions for the project
                    release_definitions = get_release_definitions(session, instance, collection_name, project_name, pat_token)
                    
                    # Apply rate limiting
                    time.sleep(rate_limit_delay)
                    
                    if release_definitions:
                        print(f"  Found {len(release_definitions)} release pipeline(s)")
                        logging.info(f"Found {len(release_definitions)} release pipelines in {collection_name}/{project_name}")
                        
                        for release_definition in release_definitions:
                            definition_id = release_definition['id']
                            pipeline_name = release_definition['name']
                            
                            # Fetch detailed release definition
                            definition_details = get_release_definition_details(session, instance, collection_name, project_name, definition_id, pat_token)
                            
                            # Apply rate limiting
                            time.sleep(rate_limit_delay)
                            
                            if definition_details:
                                file_path = save_to_files(collection_name, project_name, pipeline_name, definition_id, definition_details, output_dir)
                                logging.info(f"Saved release pipeline: {collection_name}/{project_name}/{pipeline_name} (ID: {definition_id}) to {file_path}")
                            else:
                                error_msg = f"Failed to fetch details for release pipeline: {pipeline_name} (ID: {definition_id})"
                                print(f"  {error_msg}")
                                logging.error(f"{error_msg} in {collection_name}/{project_name}")
                    else:
                        print(f"  No release pipelines found in project '{project_name}'")
                        logging.info(f"No release pipelines found in project {collection_name}/{project_name}")

                    # Log the project as processed
                    with open(log_file_path, 'a') as log_file:
                        log_file.write(f"{project_entry}\n")
                    
                    processed_entries.append(project_entry)
                    print(f"  Project '{project_name}' processing complete")
                    logging.info(f"Completed processing for project: {collection_name}/{project_name}")

                else:
                    error_msg = f"Project '{project_name}' not found in collection '{collection_name}' metadata."
                    print(f"\n{error_msg}")
                    logging.error(error_msg)

    print(f"\n{'='*60}")
    print(f"Script execution completed!")
    print(f"Output directory: {output_dir}")
    print(f"Logs directory: {logs_dir}")
    print(f"Detailed log file: {log_filename}")
    print(f"{'='*60}")
    
    logging.info("=" * 80)
    logging.info("SCRIPT COMPLETED SUCCESSFULLY")
    logging.info("=" * 80)

if __name__ == "__main__":
    main()