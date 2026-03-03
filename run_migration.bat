@echo off
echo ============================================================================
echo AZURE DEVOPS RELEASE PIPELINE MIGRATION TOOLKIT
echo ============================================================================
echo.

set BASE_PATH=C:\Users\2000147244\Downloads\Pipeline_Definition_Pattern_Identifier
set RELEASE_PATH=%BASE_PATH%\RELEASE\Output\kolappan88\Kols-1st-test\release_definitions
set ORIG_PATH=%BASE_PATH%\Output\kolappan88\Kols-1st-test\release_definitions

echo PHASE 1: DISCOVERY & COLLECTION
echo ----------------------------------------
python Release_Pipeline_Discovery.py --server_host_name dev.azure.com --collection_name kolappan88 --pat_token_file pat.txt --project_file project.txt --api_version 7.0 --protocol https
echo.
pause

echo PHASE 2: ANALYSIS & PATTERN IDENTIFICATION
echo ----------------------------------------
python Extract_Task_list_From_Release_Definition_Json.py "%ORIG_PATH%"
python Release_Pipeline_Pattern_Identifier.py "%RELEASE_PATH%" --output_excel Pipeline_Patterns.xlsx
echo.
pause

echo PHASE 3: SIMPLIFICATION & REVIEW
echo ----------------------------------------
python simplify_pipeline.py "%RELEASE_PATH%" -o simplified_output
echo.
pause

echo PHASE 4: ENVIRONMENT & APPROVAL MIGRATION
echo ----------------------------------------
python environment.py --org kolappan88 --project "Kols-1st-test" --json-folder "%RELEASE_PATH%" --pat-file "%BASE_PATH%\RELEASE\pat.txt" --create-envs
echo.
pause

echo PHASE 5: YAML CONVERSION
echo ----------------------------------------
python json_to_yaml.py "%RELEASE_PATH%"
echo.
echo ============================================================================
echo MIGRATION COMPLETE!
echo ============================================================================
pause