# Setup Guide

## Installation

### Method 1: Using Conda Environment (Recommended)

1. **Install Miniconda/Anaconda** (if not already installed)
   - Download from: https://docs.conda.io/en/latest/miniconda.html

2. **Create the conda environment from the YAML file:**
   ```bash
   conda env create -f GitHubPullRequestParser.yml
   ```

3. **Activate the environment:**
   ```bash
   conda activate GitHubPullRequestParser
   ```

4. **Verify installation:**
   ```bash
   python --version
   pip list
   ```

### Method 2: Using pip (Alternative)

1. **Install Python** (if not already installed)
   - Python 3.7 or higher is required
   - Download from: https://www.python.org/downloads/

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

   Or install directly:
   ```bash
   pip install requests
   ```

## GitHub Authentication (Optional but Recommended)

For public repositories, authentication is optional. For private repositories or to avoid rate limits, you need to authenticate.

### Option 1: Environment Variable (Recommended)
Set the `GITHUB_TOKEN` environment variable with your GitHub Personal Access Token:

**Windows (PowerShell):**
```powershell
$env:GITHUB_TOKEN = "your_token_here"
```

**Windows (Command Prompt):**
```cmd
set GITHUB_TOKEN=your_token_here
```

**Linux/Mac:**
```bash
export GITHUB_TOKEN=your_token_here
```

### Option 2: Pass token directly in code
You can modify the script to pass the token directly when initializing the parser:
```python
parser = GitHubPRParser(token="your_token_here")
```

### How to Create a GitHub Personal Access Token

1. Go to GitHub Settings → Developer settings → Personal access tokens → Tokens (classic)
2. Click "Generate new token" → "Generate new token (classic)"
3. Give it a name (e.g., "PR Parser")
4. Select scopes:
   - For public repos: `public_repo`
   - For private repos: `repo` (full control)
5. Click "Generate token" and copy it

## Usage

### Method 1: Using Batch File (Windows - Recommended)

If you're using the conda environment, simply run:
```cmd
GitHubPullRequestParser.bat
```

This will automatically activate the conda environment and run the script.

### Method 2: Using PowerShell Function (Windows)

1. **Add to your PowerShell profile** (one-time setup):

   First, ensure you have a `$MachineSpecificPaths` variable in your PowerShell profile with the parser directory:
   ```powershell
   $MachineSpecificPaths = @{
       GitHubPullRequestParserDirectory = "C:\Users\Ivan\Development\GitHub\GitHubPullRequestParser"
   }
   ```

2. **Load the function** by dot-sourcing the script:
   ```powershell
   . "C:\Users\Ivan\Development\GitHub\GitHubPullRequestParser\GitHubPullRequestParser.ps1"
   ```

3. **Run the parser** from anywhere:
   ```powershell
   GitHubPullRequestParser
   ```

### Method 3: Direct Python Execution

1. Activate the conda environment (if using conda):
   ```bash
   conda activate GitHubPullRequestParser
   ```

2. Run the script:
   ```bash
   python GitHubPullRequestParser.py
   ```

3. Enter the PR URL when prompted:
   ```
   Enter GitHub PR URL: https://github.com/futurama-soft/asseto/pull/3
   ```

4. Optionally add custom ignore patterns (comma-separated):
   ```
   Enter custom ignore patterns: **/test/*, **/*.min.js
   ```

5. The script will generate a markdown file on your Desktop with the name `pr_<number>_review.md`

### Programmatic Usage

You can also use the parser in your own Python scripts:

```python
from GitHubPullRequestParser import GitHubPRParser

# Initialize parser
parser = GitHubPRParser()

# Add custom ignore patterns
parser.add_ignore_patterns(['**/test/*', '**/*.min.js'])

# Parse PR
parser.parse('https://github.com/owner/repo/pull/123')
```

## Default Ignore Patterns

The script comes with default ignore patterns similar to `.gitignore`:

- `**/Migrations/*` - Database migration files
- `**/migrations/*` - Migration files (lowercase)
- `**/*.min.js` - Minified JavaScript
- `**/*.min.css` - Minified CSS
- `**/node_modules/*` - Node.js dependencies
- `**/package-lock.json` - Package lock files
- `**/yarn.lock` - Yarn lock files

## Output Format

The generated markdown file contains three main sections:

1. **Description** - List of all files with placeholder for manual descriptions
2. **Code** - Actual code changes with old/new sections
3. **Feedback** - PR review comments and conversations

Files are automatically categorized as:
- **Backend** - Files in `api/` folder or with extensions: `.cs`, `.java`, `.py`, `.go`
- **Frontend** - Files in `ui/`/`frontend/` folders or with extensions: `.ts`, `.tsx`, `.jsx`, `.vue`
- **Other** - Everything else

## Troubleshooting

### Rate Limit Errors
If you get rate limit errors, authenticate with a GitHub token (see Authentication section above).

### Permission Errors
Make sure you have access to the repository (for private repos) and that your token has the correct scopes.

### Desktop Path Not Found
The script saves to `~/Desktop` (or `%USERPROFILE%\Desktop` on Windows). If your Desktop is in a different location, you can modify the `save_to_desktop` method in the script.
