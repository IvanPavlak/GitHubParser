# GitHub Pull Request Parser

GitHub Pull Request Parser is a Python CLI tool that fetches a GitHub pull request and creates structured markdown output for note taking in your favourite note app (I use Obsidian btw).

## Highlights

- Works with public and private repositories
- Handles paginated GitHub API responses for files and comments
- Configurable ignore rules through `PRIgnore.txt`
- Configurable extra extraction rules through `SeparateExtractionList.txt`
- Generates a desktop output folder for the selected PR
- Produces diff-style markdown for both main code output and separate extraction files

## Requirements

- Python 3.8+ (Python 3.12 recommended)
- requests 2.31.0
- GitHub personal access token for private repos (recommended for all usage to avoid low rate limits)

## Installation

### Conda

```bash
conda env create -f GitHubPullRequestParser.yml
conda activate GitHubPullRequestParser
```

Note:

- `GitHubPullRequestParser.yml` currently contains a machine-specific prefix.
- If env creation fails on your machine, remove the prefix line and retry.

### pip

```bash
python -m pip install requests==2.31.0
```

## Authentication

For private repositories, set `GITHUB_TOKEN` before running.

PowerShell:

```powershell
$env:GITHUB_TOKEN = "your_token_here"
```

CMD:

```cmd
set GITHUB_TOKEN=your_token_here
```

Create token: https://github.com/settings/tokens

Scopes:

- `private repos: repo`
- `public-only access: public_repo`

## Usage

### Recommended (cross-platform)

```bash
python GitHubPullRequestParser.py
```

The script prompts for:

1. Whether the repository is private
2. The PR URL

Example URL:

```text
https://github.com/owner/repo/pull/123
```

### Windows helper scripts

This repository also includes:

- `GitHubPullRequestParser.bat`
- `GitHubPullRequestParser.ps1`

Important:

- Both currently use machine-specific hardcoded paths.
- Update these paths before using them on another machine.

## Output

For PR 123 in org/repo, output is written to:

```text
<Desktop>/PR_123_org_repo/
```

Main files:

- `Description.md`
- `Code.md`
- `Feedback.md`
- `PRIgnore_Report.txt`
- `SeparateExtraction_Report.txt`

Additional extracted files (from SeparateExtractionList.txt) are created in the same root output folder, for example:

- `appsettings.Development.json.md`
- `CHANGELOG.md.md`
- `MyProject.csproj.md`

If multiple matched files share the same source filename, a numeric suffix is added to avoid overwrite.

## Configuration

### PRIgnore.txt

Controls which files are ignored for the main parsing outputs.

Pattern behavior:

- One glob pattern per line
- Lines starting with `#` are comments
- Optional negation with `!pattern`
- Last matching rule wins

### SeparateExtractionList.txt

Controls which changed files get extra standalone markdown diff files in the output root.

Current starter patterns include:

- appsettings JSON files
- changelog markdown files
- csproj files

## Output format details

### Code.md and separate extraction files

Diffs are rendered in markdown code blocks with old/new sections when patch data is available.

When GitHub does not provide textual patch data for a file, the separate extraction file still gets created with a markdown note and status.

### Feedback.md

Comment snippets are extracted from diff hunks with this behavior:

- Exact selected range when start_line and line are available
- Otherwise line with surrounding context
- Tail fallback when line metadata is unavailable

## Troubleshooting

### 404 Not Found

Common causes:

- private repository without token
- incorrect PR URL
- missing repository access

### Missing files in output

- Check `PRIgnore_Report.txt` for ignored files
- Check `SeparateExtraction_Report.txt` for files matched by `SeparateExtractionList.txt`
- Verify patterns in `PRIgnore.txt` and `SeparateExtractionList.txt`

### Rate limit issues

Unauthenticated GitHub API usage is limited. Set `GITHUB_TOKEN` to increase limits.

## Repository files

- `GitHubPullRequestParser.py`: main parser
- `PRIgnore.txt`: ignore rules
- `SeparateExtractionList.txt`: rules for extra extracted markdown files
- `LICENSE`: Unlicense (public-domain dedication)
- `GitHubPullRequestParser.yml`: conda environment spec
- `GitHubPullRequestParser.bat`: batch launcher (path-dependent)
- `GitHubPullRequestParser.ps1`: PowerShell wrapper (path-dependent)

## License

This project is released under the [Unlicense](https://unlicense.org), which is a public-domain dedication.

In practical terms: you can copy, modify, use, publish, and reuse this code (including commercially) with no attribution requirement.

## Contributing

Issues and pull requests are welcome.

When proposing changes or addressing issues please include:

- what changed
- why it changed
- expected output example
- what is the issue and how to reproduce it

---
