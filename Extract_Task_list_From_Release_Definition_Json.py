"""
Developer: Kolappan Mayilvanan
Script: Extract_Task_List_From_Release_Definition_Json.py
Version: 3.1 - Added --json-output argument
Description: This script extracts task information from release pipeline JSON files.
             It navigates through environments → deployPhases → workflowTasks structure
             and exports to CSV with detailed context.
"""

import json
import os
import csv
import sys
from datetime import datetime

def print_header(message):
    """Print formatted header"""
    print("\n" + "=" * 70)
    print(f" {message}")
    print("=" * 70)

def print_section(message):
    """Print section header"""
    print("\n" + "-" * 50)
    print(f" {message}")
    print("-" * 50)

def validate_input_directory(input_directory_path):
    """Validate if directory exists and is accessible"""
    if not os.path.exists(input_directory_path):
        print(f"Error: Input directory '{input_directory_path}' does not exist.")
        return False
    if not os.path.isdir(input_directory_path):
        print(f"Error: '{input_directory_path}' is not a directory.")
        return False
    return True

def extract_tasks_from_release_pipeline(json_content, source_filename, csv_writer):
    """
    Extract tasks from release pipeline JSON structure
    Structure: environments → deployPhases → workflowTasks
    """
    file_has_data = False
    task_count = 0
    
    # Check if content is a dictionary (single release definition)
    if isinstance(json_content, dict):
        # Get release definition metadata
        release_name = json_content.get('name', 'Unknown Release')
        release_id = json_content.get('id', 'Unknown ID')
        
        # Get environments array
        environments = json_content.get('environments', [])
        
        for env_index, environment in enumerate(environments):
            environment_name = environment.get('name', f'Unknown Environment {env_index + 1}')
            environment_rank = environment.get('rank', 'Unknown Rank')
            environment_id = environment.get('id', 'Unknown ID')
            
            # Get deployPhases array
            deploy_phases = environment.get('deployPhases', [])
            
            for phase_index, phase in enumerate(deploy_phases):
                phase_name = phase.get('name', f'Unknown Phase {phase_index + 1}')
                phase_type = phase.get('phaseType', 'Unknown Type')
                phase_rank = phase.get('rank', 'Unknown Rank')
                
                # Get workflowTasks array
                workflow_tasks = phase.get('workflowTasks', [])
                
                for task_item in workflow_tasks:
                    # Extract task information
                    task_id = task_item.get('taskId', '')
                    task_name = task_item.get('name', '')
                    task_version = task_item.get('version', '')
                    task_enabled = task_item.get('enabled', True)
                    task_condition = task_item.get('condition', '')
                    task_continue_on_error = task_item.get('continueOnError', False)
                    task_timeout = task_item.get('timeoutInMinutes', 0)
                    task_always_run = task_item.get('alwaysRun', False)
                    task_ref_name = task_item.get('refName', '')
                    
                    # Skip if task_id is empty
                    if not task_id:
                        continue
                    
                    # Write to CSV
                    csv_writer.writerow([
                        source_filename,                 # Source file
                        release_name,                    # Release name
                        release_id,                      # Release ID
                        environment_name,                # Environment name
                        environment_rank,                # Environment rank
                        environment_id,                  # Environment ID
                        phase_name,                       # Phase name
                        phase_type,                       # Phase type
                        phase_rank,                       # Phase rank
                        task_name,                        # Task display name
                        task_ref_name,                    # Task reference name
                        task_id,                          # Task ID
                        task_version,                     # Task version
                        str(task_enabled),                # Whether task is enabled
                        task_condition,                   # Task condition
                        str(task_continue_on_error),      # Continue on error flag
                        str(task_timeout),                 # Timeout in minutes
                        str(task_always_run)               # Always run flag
                    ])
                    file_has_data = True
                    task_count += 1
    
    return file_has_data, task_count

def parse_command_line_arguments():
    """Parse and validate command line arguments"""
    if len(sys.argv) < 2:
        print("\nError: At least one argument is required!")
        print("\nUsage: python script_name.py [options]")
        print("\nRequired Arguments (choose one):")
        print("  <input_directory_path>   : Path to directory containing release pipeline JSON files (positional argument)")
        print("  --json-output <path>     : Path to directory containing release pipeline JSON files (named argument)")
        print("\nOptional Arguments:")
        print("  --output_csv <filename>  : Custom output CSV filename (default: release_pipeline_tasks_output.csv)")
        print("  --log_file <filename>    : Custom log filename (default: unprocessed_release_files.log)")
        print("  --help                    : Show this help message")
        print("\nExamples:")
        print("  python Extract_Task_List_From_Release_Definition_Json.py C:\\Output\\MyCollection")
        print("  python Extract_Task_List_From_Release_Definition_Json.py --json-output ./json_files --output_csv my_tasks.csv")
        return None, None, None
    
    # Initialize variables
    input_directory_path = None
    output_csv_file = 'release_pipeline_tasks_output.csv'
    log_file_name = 'unprocessed_release_files.log'
    
    # Parse arguments
    i = 1
    while i < len(sys.argv):
        if sys.argv[i] == '--json-output' and i + 1 < len(sys.argv):
            input_directory_path = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--output_csv' and i + 1 < len(sys.argv):
            output_csv_file = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--log_file' and i + 1 < len(sys.argv):
            log_file_name = sys.argv[i + 1]
            i += 2
        elif sys.argv[i] == '--help':
            print_help()
            sys.exit(0)
        elif sys.argv[i].startswith('--'):
            print(f"\nWarning: Unknown argument '{sys.argv[i]}' - ignoring")
            i += 1
        else:
            # Positional argument (input directory)
            if input_directory_path is None:
                input_directory_path = sys.argv[i]
            else:
                print(f"\nWarning: Unexpected positional argument '{sys.argv[i]}' - ignoring")
            i += 1
    
    # Check if input directory was provided
    if input_directory_path is None:
        print("\nError: No input directory specified!")
        print("Please provide either a positional argument or use --json-output <path>")
        return None, None, None
    
    return input_directory_path, output_csv_file, log_file_name

def print_help():
    """Print help information"""
    print("\nHelp: Extract Task List From Release Definition JSON")
    print("=" * 50)
    print("This script extracts task information from release pipeline JSON files")
    print("and exports to CSV with detailed context.")
    print("\nUsage: python script_name.py [options]")
    print("\nRequired Arguments (choose one):")
    print("  <input_directory_path>   : Path to directory containing release pipeline JSON files (positional argument)")
    print("  --json-output <path>     : Path to directory containing release pipeline JSON files (named argument)")
    print("\nOptional Arguments:")
    print("  --output_csv <filename>  : Custom output CSV filename (default: release_pipeline_tasks_output.csv)")
    print("  --log_file <filename>    : Custom log filename (default: unprocessed_release_files.log)")
    print("  --help                    : Show this help message")
    print("\nExamples:")
    print("  # Using positional argument")
    print("  python Extract_Task_List_From_Release_Definition_Json.py C:\\Output\\MyCollection")
    print("\n  # Using --json-output argument")
    print("  python Extract_Task_List_From_Release_Definition_Json.py --json-output ./json_files")
    print("\n  # Using all arguments")
    print("  python Extract_Task_List_From_Release_Definition_Json.py --json-output ./json_files --output_csv my_tasks.csv --log_file my_errors.log")

def main():
    """Main function to process release pipeline JSON files"""
    
    print_header("RELEASE PIPELINE TASK EXTRACTION TOOL")
    
    # Parse command line arguments
    input_directory_path, output_csv_file, log_file_name = parse_command_line_arguments()
    
    if input_directory_path is None:
        sys.exit(1)
    
    # Validate input directory
    if not validate_input_directory(input_directory_path):
        sys.exit(1)
    
    print(f"\nInput Configuration:")
    print(f"  JSON Files Directory : {input_directory_path}")
    print(f"  Output CSV File      : {output_csv_file}")
    print(f"  Log File             : {log_file_name}")
    
    # Initialize counters
    total_json_files_found = 0
    files_processed_successfully = 0
    unprocessed_files_list = []
    total_tasks_extracted = 0
    
    current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Open the CSV file for writing
    try:
        with open(output_csv_file, mode='w', newline='', encoding='utf-8') as csv_file_handle:
            csv_writer = csv.writer(csv_file_handle)
            # Write header row
            csv_writer.writerow([
                'Source_File_Name',
                'Release_Name',
                'Release_Id',
                'Environment_Name',
                'Environment_Rank',
                'Environment_Id',
                'Phase_Name',
                'Phase_Type',
                'Phase_Rank',
                'Task_Display_Name',
                'Task_Reference_Name',
                'Task_Id',
                'Task_Version',
                'Task_Enabled',
                'Task_Condition',
                'Continue_On_Error',
                'Timeout_Minutes',
                'Always_Run'
            ])
            
            print_section("SCANNING DIRECTORY")
            
            # Walk through the directory
            for root_directory, sub_directories, files_in_directory in os.walk(input_directory_path):
                json_files = [file_name for file_name in files_in_directory if file_name.endswith(".json")]
                
                if json_files:
                    relative_path = os.path.relpath(root_directory, input_directory_path)
                    if relative_path == '.':
                        print(f"\nRoot directory: {len(json_files)} JSON file(s)")
                    else:
                        print(f"\nSubdirectory: {relative_path} - {len(json_files)} JSON file(s)")
                
                for json_filename in json_files:
                    total_json_files_found += 1
                    json_file_full_path = os.path.join(root_directory, json_filename)
                    
                    print(f"  Processing: {json_filename}", end='', flush=True)
                    
                    try:
                        with open(json_file_full_path, 'r', encoding='utf-8') as json_file_handle:
                            json_content = json.load(json_file_handle)
                            
                            # Extract tasks
                            file_has_data, task_count = extract_tasks_from_release_pipeline(
                                json_content, json_filename, csv_writer
                            )
                            
                            if not file_has_data:
                                unprocessed_files_list.append(json_filename)
                                print(f" - No tasks found")
                            else:
                                files_processed_successfully += 1
                                total_tasks_extracted += task_count
                                print(f" - {task_count} task(s) extracted")
                                
                    except json.JSONDecodeError as json_error:
                        print(f" - ERROR: Invalid JSON format")
                        unprocessed_files_list.append(json_filename)
                    except Exception as generic_error:
                        print(f" - ERROR: Unexpected error")
                        unprocessed_files_list.append(json_filename)
    
    except Exception as file_error:
        print(f"\nError: Failed to create CSV file: {str(file_error)}")
        sys.exit(1)
    
    # Save unprocessed file names to the log file
    if unprocessed_files_list:
        try:
            with open(log_file_name, mode='w', encoding='utf-8') as log_file_handle:
                log_file_handle.write(f"Release Pipeline Task Extraction - Unprocessed Files Log\n")
                log_file_handle.write(f"Generated: {current_timestamp}\n")
                log_file_handle.write(f"JSON Files Directory: {input_directory_path}\n")
                log_file_handle.write("=" * 70 + "\n\n")
                log_file_handle.write("Files that could not be processed or had no valid tasks:\n")
                log_file_handle.write("-" * 50 + "\n")
                for file_name in sorted(unprocessed_files_list):
                    log_file_handle.write(f"{file_name}\n")
                log_file_handle.write(f"\nTotal unprocessed files: {len(unprocessed_files_list)}")
            print(f"\nUnprocessed files log saved to: {log_file_name}")
        except Exception as log_error:
            print(f"\nWarning: Could not write log file: {str(log_error)}")
    
    # Print final statistics
    print_header("EXTRACTION SUMMARY")
    print(f"\n{'JSON Files Directory:':<30} {input_directory_path}")
    print(f"{'Total JSON Files Found:':<30} {total_json_files_found}")
    print(f"{'Files Processed Successfully:':<30} {files_processed_successfully}")
    print(f"{'Files Unprocessed:':<30} {len(unprocessed_files_list)}")
    print(f"{'Total Tasks Extracted:':<30} {total_tasks_extracted}")
    
    if total_json_files_found > 0:
        success_rate = (files_processed_successfully / total_json_files_found * 100)
        print(f"{'Success Rate:':<30} {success_rate:.1f}%")
    
    if unprocessed_files_list:
        print(f"\n{'Output CSV File:':<30} {output_csv_file}")
        print(f"{'Unprocessed Log File:':<30} {log_file_name}")
        
        # Show sample of unprocessed files
        if len(unprocessed_files_list) <= 10:
            print("\nUnprocessed Files:")
            for unprocessed_file in unprocessed_files_list:
                print(f"  - {unprocessed_file}")
        else:
            print(f"\nFirst 5 Unprocessed Files (see {log_file_name} for complete list):")
            for unprocessed_file in unprocessed_files_list[:5]:
                print(f"  - {unprocessed_file}")
            print(f"  ... and {len(unprocessed_files_list) - 5} more")
    else:
        print(f"\n{'Output CSV File:':<30} {output_csv_file}")
        print("\n✓ All files processed successfully! No unprocessed files.")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    main()