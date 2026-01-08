@echo off

set "python_script=C:\Users\Ivan\Development\GitHub\GitHubPullRequestParser\GitHubPullRequestParser.py"

:: Activate the conda environment and run the Python script
call "C:\Users\Ivan\miniconda3\Scripts\activate.bat" "C:\Users\Ivan\miniconda3"
call conda activate GitHubPullRequestParser
python "%python_script%"
