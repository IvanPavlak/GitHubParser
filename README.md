# GitHub Parser

Extracts information from a GitHub **pull request or commit** and formats it into
structured markdown files. You can extract everything, or selectively pull just
one section (for example, only the feedback/comments).

## Highlights

- Works with pull requests **and** commits
- Works with public and private repositories
- Selective extraction: choose any of `description`, `code`, `feedback`
- Handles paginated GitHub API responses for files and comments
- Configurable ignore rules through `Ignore.txt`
- Configurable extra extraction rules through `SeparateExtractionList.txt`
- Generates a desktop output folder for the selected PR or commit
- Produces diff-style markdown for both main code output and separate extraction files

## Requirements

- Python 3.8+ (Python 3.12 recommended)
- requests 2.31.0
- GitHub personal access token for private repos (recommended for all usage to avoid low rate limits)

## Installation

### Conda

```bash
conda env create -f GitHubParser.yml
conda activate GitHubParser
```

Note:

- `GitHubParser.yml` is portable and does not include a machine-specific prefix.

### pip

```bash
python -m pip install requests==2.31.0
```

## Authentication

For private repositories (and to avoid low rate limits), authenticate with a token.
For security the token is **never accepted as a command-line argument** - it would leak
into shell history and process listings. Provide it in one of two ways:

- Set the `GITHUB_TOKEN` environment variable, or
- Enter it at the secure, no-echo prompt the script shows for a private repo.

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
python GitHubParser.py
```

Run with no arguments and the script prompts for:

1. Whether the repository is private
2. Which sections to extract (default: all)
3. The PR or commit URL

Example URLs:

```text
https://github.com/owner/repo/pull/123
https://github.com/owner/repo/commit/<sha>
```

A commit URL may include a `#diff-<hash>` fragment (a link to a specific file on
the page); it is ignored.

### Command-line flags

All prompts can be skipped with flags. Anything not provided falls back to an
interactive prompt.

```bash
# Extract only feedback (comments) from a commit
python GitHubParser.py --only feedback https://github.com/owner/repo/commit/<sha>

# Extract code + feedback from a PR of a public repo, no prompts
python GitHubParser.py --sections code,feedback --public https://github.com/owner/repo/pull/123

# Private repo, token from the environment
python GitHubParser.py --private --only feedback <url>
```

| Flag                         | Description                                                                                                                        |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- |
| `url` (positional)           | PR or commit URL. Prompted if omitted.                                                                                             |
| `-s`, `--sections`, `--only` | Comma-separated: `description`, `code`, `feedback`, or `all`. Alias: `comments` = `feedback`. Prompted if omitted (default `all`). |
| `--private` / `--public`     | Skip the private/public prompt.                                                                                                    |

There is deliberately no token flag: the token comes only from `GITHUB_TOKEN` or the
secure prompt (see [Authentication](#authentication)).

### Windows helper scripts

This repository also includes:

- `GitHubParser.bat`
- `GitHubParser.ps1`

Important:

- `GitHubParser.bat` reads machine-specific values from `GitHubParser.config.bat`.
- Update `GitHubParser.config.bat` before first use.

The `GitHubParser` PowerShell function exposes the same options as the Python CLI and forwards
them through `GitHubParser.bat` to `GitHubParser.py`, so it can be driven directly from
PowerShell in the same manner. Anything omitted falls through to the interactive prompt.

```powershell
# Interactive
GitHubParser

# Extract only feedback from a commit
GitHubParser -Only feedback https://github.com/owner/repo/commit/<sha>

# Code + feedback from a public PR, no prompts
GitHubParser -Sections code,feedback -Public https://github.com/owner/repo/pull/123

# Private repo: prompt (no echo) for a token, never placing it on the command line
GitHubParser -Private -Token (Read-Host -AsSecureString) -Only feedback <url>
```

| Parameter              | Description                                                                                                                                                                                           |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `-Url` (positional)    | PR or commit URL. Prompted if omitted.                                                                                                                                                                |
| `-Sections` / `-Only`  | Comma-separated: `description`, `code`, `feedback`, or `all`. Alias: `comments` = `feedback`. Accepts an array (`code,feedback`).                                                                     |
| `-Token`               | GitHub token as a **SecureString** (e.g. `(Read-Host -AsSecureString)`). Injected via the `GITHUB_TOKEN` environment variable for the child process only, then cleared - never passed as an argument. |
| `-Private` / `-Public` | Skip the private/public prompt.                                                                                                                                                                       |

### Launcher config

`GitHubParser.config.bat` contains these editable values:

- `conda_prefix`: full path to your conda environment, for example `C:\\Users\\your-user\\miniconda3\\envs\\GitHubParser`
- `conda_base`: full path to your conda installation, for example `C:\\Users\\your-user\\miniconda3`
- `python_script`: full path to `GitHubParser.py` on your machine

The batch launcher uses this config file to:

- call `%conda_base%\\Scripts\\activate.bat` `%conda_base%`
- run `conda activate %conda_prefix%`
- execute `python %python_script% %*` (any arguments passed to `GitHubParser.bat` are forwarded to the Python CLI)

## Output

Output is written to a folder on your desktop, named by source:

```text
<Desktop>/PR_123_org_repo/          # for a pull request
<Desktop>/Commit_d974808_org_repo/  # for a commit (short SHA)
```

Files written (only for the sections you requested):

- `Description.md` (section `description`)
- `Code.md` (section `code`)
- `Feedback.md` (section `feedback`)
- `Ignore_Report.txt` (only when `description` or `code` is requested)
- `SeparateExtraction_Report.txt` (only when `description` or `code` is requested)

Additional extracted files (from `SeparateExtractionList.txt`) are created in the
same root output folder, for example:

- `appsettings.Development.json.md`
- `CHANGELOG.md.md`
- `MyProject.csproj.md`

If multiple matched files share the same source filename, a numeric suffix is added to avoid overwrite.

## Configuration

### Ignore.txt

Controls which files are ignored for the main parsing outputs.

Pattern behavior:

- One glob pattern per line
- Lines starting with `#` are comments
- Optional negation with `!pattern`
- Last matching rule wins

### SeparateExtractionList.txt

Controls which changed files get standalone markdown diff files in the output root.

Files that match these patterns are excluded from main outputs (`Description.md` and `Code.md`) so they appear only in their dedicated extracted files.

Current starter patterns include:

- appsettings JSON files
- changelog markdown files
- csproj files

## Output format details

### Code.md and separate extraction files

Diffs are rendered in markdown code blocks with old/new sections when patch data is available.

Files matched by `SeparateExtractionList.txt` are not included in `Code.md`; they are written only to separate extracted markdown files.

When GitHub does not provide textual patch data for a file, the separate extraction file still gets created with a markdown note and status.

### Feedback.md

All feedback on a pull request is captured, not just inline code notes:

- Inline review comments (anchored to a diff line)
- Conversation-tab comments (general discussion, not attached to code)
- Review summaries (the message submitted with an Approve / Comment / Request-changes review)

Comments not attached to a file are grouped under a `General` heading. For a commit,
both file-level and general commit comments are captured the same way.

Code snippets for anchored comments are extracted with this behavior:

- For PR review comments, the code snippet comes from the comment's diff hunk
- For commit comments (which have no diff hunk), the snippet comes from the file's patch using the comment line
- Exact selected range when start_line and line are available
- Otherwise the line with surrounding context
- Tail fallback when line metadata is unavailable

## Troubleshooting

### 404 Not Found

Common causes:

- private repository without token
- incorrect PR/commit URL
- missing repository access

### Missing files in output

- Check `Ignore_Report.txt` for ignored files
- Check `SeparateExtraction_Report.txt` for files matched by `SeparateExtractionList.txt`
- Verify patterns in `Ignore.txt` and `SeparateExtractionList.txt`

### Rate limit issues

Unauthenticated GitHub API usage is limited. Set `GITHUB_TOKEN` to increase limits.

## Repository files

- `GitHubParser.py`: main parser
- `Ignore.txt`: ignore rules
- `SeparateExtractionList.txt`: rules for extra extracted markdown files
- `LICENSE`: MIT License
- `GitHubParser.yml`: conda environment spec
- `GitHubParser.bat`: batch launcher (path-dependent)
- `GitHubParser.ps1`: PowerShell wrapper (path-dependent)

## License

This project is released under the MIT License.

In practical terms: you can copy, modify, use, publish, and reuse this code (including commercially), as long as the license notice is included with substantial portions of the software.

## Contributing

Issues and pull requests are welcome.

When proposing changes or addressing issues please include:

- what changed
- why it changed
- expected output example
- what is the issue and how to reproduce it

---
