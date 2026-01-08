# GitHub Pull Request Parser

A Python tool to extract and format GitHub Pull Request information into organized markdown files.

## Requirements

- Python 3.12+ (or 3.7+)
- Miniconda or Anaconda (recommended)
- Python package: `requests>=2.31.0`
- GitHub Personal Access Token (for private repositories)

## Features

- Parses GitHub PR URLs and extracts all file changes and comments
- Supports both public and private repositories (with authentication)
- Filters files using customizable ignore patterns via `PRIgnore.txt` (similar to .gitignore)
- Categorizes files as Backend, Frontend, or Other
- Generates separate markdown files for:
  - **Description.md** - List of all changed files with placeholder descriptions
  - **Code.md** - All code changes with old/new sections
  - **Feedback.md** - All PR review comments and conversations
  - **PRIgnore_Report.txt** - Report showing patterns used and files that were ignored
- Creates an organized folder on your Desktop: `PR_<number>_<repo_name>`
- Handles large PRs (tested with 261+ files)

## Quick Start

1. **Create conda environment:**
   ```bash
   conda env create -f GitHubPullRequestParser.yml
   ```

2. **Set up GitHub authentication** (required for private repos):

   Create a Personal Access Token:
   - Go to: https://github.com/settings/tokens
   - Click "Generate new token" → "Generate new token (classic)"
   - Give it a name (e.g., "PR Parser")
   - Select scope: `repo` (for private repos) or `public_repo` (for public only)
   - Click "Generate token" and copy it

   Set as environment variable:
   ```powershell
   # PowerShell (temporary - current session only)
   $env:GITHUB_TOKEN = "your_token_here"

   # Or add to your PowerShell profile for permanent setup
   notepad $PROFILE
   # Add: $env:GITHUB_TOKEN = "your_token_here"
   ```

   Or set in batch file:
   ```batch
   # Edit GitHubPullRequestParser.bat and add before python command:
   set GITHUB_TOKEN=your_token_here
   ```

3. **Configure ignore patterns** (optional):

   Edit `PRIgnore.txt` in the repository to customize which files to ignore:
   ```bash
   notepad PRIgnore.txt
   ```

   Default patterns include migrations, minified files, and dependencies. Add your own patterns as needed.

4. **Run the parser:**
   ```cmd
   GitHubPullRequestParser.bat
   ```
   Or with PowerShell:
   ```powershell
   GitHubPullRequestParser
   ```

5. **Enter PR URL when prompted:**
   ```
   https://github.com/owner/repo/pull/123
   ```

6. **Find your files on Desktop:**
   - A folder named `PR_123_owner_repo` will be created
   - Contains: Description.md, Code.md, Feedback.md, PRIgnore_Report.txt

## Output Structure

```
Desktop/
└── PR_3_futurama-soft_asseto/
    ├── Description.md         # File list with description placeholders
    ├── Code.md                # All code changes (old/new sections)
    ├── Feedback.md            # All PR comments and conversations
    └── PRIgnore_Report.txt    # Report showing patterns used and ignored files
```

### Example: Description.md
```markdown
# Description

## Backend

### `api/src/Api/Artworks/ArtworkEndpointGroup.cs`

- Description

## Frontend

### `ui/src/api/auth.ts`

- Description
```

### Example: Code.md
Shows all code changes with old/new sections for easy comparison:
```markdown
# Code

## Backend

### `api/src/Api/Artworks/ArtworkEndpointGroup.cs`

```cs
// Old
...
protected override void MapCustomEndpoints(RouteGroupBuilder group)
{
    base.MapCustomEndpoints(group);
}
...

// New
...
protected override void MapGridPropertiesEndpoint(RouteGroupBuilder group)
{
    base.MapGridPropertiesEndpoint(group);
    // ... new implementation
}
...
```
```

### Example: Feedback.md
Contains all PR review comments with relevant code snippets:
```markdown
# Feedback

### `api/src/Api/Artworks/ArtworkEndpointGroup.cs`

```cs
protected override void MapCreatePropertiesEndpoint(RouteGroupBuilder group)
{
    base.MapCreatePropertiesEndpoint(group);
```

- `ReviewerUsername` → Some comment about the implementation
- `AuthorUsername` → Reply to the comment
```

### Example: PRIgnore_Report.txt
Report generated during processing showing patterns used and files that were skipped:
```
# PRIgnore Report
# This report shows which files were ignored during PR parsing

## Ignore Patterns Used
# Loaded from: PRIgnore.txt in repository
# Total patterns: 7

**/Migrations/*
**/migrations/*
**/*.min.js
**/*.min.css
**/node_modules/*
**/package-lock.json
**/yarn.lock

## Ignored Files
# Total files ignored: 15

api/src/Domain/Database/Migrations/20251107094120_initial-migration.cs
ui/package-lock.json
...
```

## Installation

### Method 1: Using Conda (Recommended)

This creates an isolated environment with Python 3.12 and all dependencies.

```bash
# Create environment from YAML file
conda env create -f GitHubPullRequestParser.yml

# Activate environment
conda activate GitHubPullRequestParser

# Verify installation
python --version
# Should show: Python 3.12.1
```

The `GitHubPullRequestParser.yml` file includes:
- Python 3.12.1
- pip 24.0
- requests 2.31.0

### Method 2: Using pip (Alternative)

If you prefer not to use Conda:

```bash
# Make sure you have Python 3.7+ installed
python --version

# Install the required package
pip install requests>=2.31.0
```

## Usage Methods

### 1. Batch File (Windows - Easiest)

Simply double-click or run from command line:
```cmd
GitHubPullRequestParser.bat
```

This automatically:
- Activates the conda environment
- Runs the Python script
- Prompts you for PR URL and ignore patterns

### 2. PowerShell Function (For Power Users)

Set up once in your PowerShell profile for easy access from anywhere:

1. Open your PowerShell profile:
   ```powershell
   notepad $PROFILE
   ```

2. Add these lines:
   ```powershell
   # Add path to machine-specific paths
   $MachineSpecificPaths = @{
       GitHubPullRequestParserDirectory = "C:\Users\Ivan\Development\GitHub\GitHubPullRequestParser"
   }

   # Load the function
   . "C:\Users\Ivan\Development\GitHub\GitHubPullRequestParser\GitHubPullRequestParser.ps1"
   ```

3. Save and reload your profile:
   ```powershell
   . $PROFILE
   ```

4. Now you can run from anywhere:
   ```powershell
   GitHubPullRequestParser
   ```

### 3. Direct Python Execution

For direct control or scripting:

```bash
# Activate environment (if using conda)
conda activate GitHubPullRequestParser

# Run the script
python GitHubPullRequestParser.py
```

Or use programmatically in your own Python scripts:
```python
from GitHubPullRequestParser import GitHubPRParser

parser = GitHubPRParser()
parser.add_ignore_patterns(['**/test/*'])
parser.parse('https://github.com/owner/repo/pull/123')
```

## Configuring Ignore Patterns

The parser reads ignore patterns from `PRIgnore.txt` in the repository (similar to `.gitignore`).

### Default Patterns Included

The `PRIgnore.txt` file comes pre-configured with sensible defaults:

- `**/Migrations/*` - Database migrations
- `**/migrations/*` - Migration files (lowercase)
- `**/*.min.js` - Minified JavaScript
- `**/*.min.css` - Minified CSS
- `**/node_modules/*` - Node dependencies
- `**/package-lock.json` - Lock files
- `**/yarn.lock` - Yarn lock files

### Adding Custom Patterns

Edit `PRIgnore.txt` to add your own patterns. Use wildcard syntax:

```bash
# Open PRIgnore.txt in your editor
notepad PRIgnore.txt
```

**Examples of custom patterns:**
- `**/test/*` - Ignore all test directories
- `**/*.spec.ts` - Ignore all spec files
- `**/dist/*` - Ignore distribution folders
- `**/build/*` - Ignore build folders
- `specific/path/file.txt` - Ignore a specific file

**Comments:** Lines starting with `#` are treated as comments and ignored.

**Report:** After processing, check `PRIgnore_Report.txt` in the output folder to see what was ignored.

## File Categorization

Files are automatically categorized into sections:

- **Backend**: Files in `api/` folder or with extensions `.cs`, `.java`, `.py`, `.go`
- **Frontend**: Files in `ui/`/`frontend/` folders or with extensions `.ts`, `.tsx`, `.jsx`, `.vue`
- **Other**: Everything else (configs, docs, etc.)

This makes it easier to review changes by technology stack.

## Troubleshooting

### 404 Error - Not Found
**Problem**: `404 Client Error: Not Found for url`

**Solutions**:
1. Repository is private - Set `GITHUB_TOKEN` environment variable
2. Check if the PR URL is correct
3. Verify you have access to the repository
4. Make sure the PR number exists

### Rate Limit Errors
**Problem**: GitHub API rate limit exceeded

**Solution**: Authenticate with a GitHub token to increase limits from 60/hour to 5000/hour

### Authentication Not Working
**Problem**: Token set but still getting 404

**Solutions**:
1. Verify token has correct scope (`repo` for private, `public_repo` for public)
2. Restart your terminal/PowerShell after setting environment variable
3. Check token hasn't expired
4. Try setting token directly in the batch file

### Missing Files in Output
**Problem**: Some files not appearing in generated markdown

**Solution**:
1. Check `PRIgnore_Report.txt` in the output folder to see if files were ignored and why
2. Edit `PRIgnore.txt` in the repository to remove unwanted patterns
3. Re-run the parser

### Large PR Performance
**Problem**: Script is slow with 200+ files

**Note**: This is expected. The script fetches all data from GitHub API, which can take time for large PRs. Be patient - all 261 files will be processed.

## Project Structure

```
GitHubPullRequestParser/
├── GitHubPullRequestParser.py       # Main Python script
├── GitHubPullRequestParser.yml      # Conda environment file
├── GitHubPullRequestParser.bat      # Windows batch launcher
├── GitHubPullRequestParser.ps1      # PowerShell function
├── PRIgnore.txt                     # Ignore patterns configuration
└── README.md                        # Complete documentation
```

**Configuration File:**
- **PRIgnore.txt**: Edit this file to customize which files to ignore during PR parsing. Uses wildcard patterns similar to .gitignore.

## Support

For issues, questions, or contributions, please refer to the GitHub repository.
