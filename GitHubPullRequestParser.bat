@echo off

set "script_dir=%~dp0"

if not exist "%script_dir%GitHubPullRequestParser.config.bat" (
	echo Missing config file: %script_dir%GitHubPullRequestParser.config.bat
	exit /b 1
)

call "%script_dir%GitHubPullRequestParser.config.bat"

if not defined conda_base (
	echo Missing required config value: conda_base
	exit /b 1
)

if not defined conda_prefix (
	echo Missing required config value: conda_prefix
	exit /b 1
)

if not defined python_script (
	echo Missing required config value: python_script
	exit /b 1
)

call "%conda_base%\Scripts\activate.bat" "%conda_base%"
call conda activate "%conda_prefix%"
python "%python_script%"
