# GitHub Parser

Extracts information from a GitHub **pull request or commit** and formats it into
structured markdown files. You can extract everything, or selectively pull just
one section (for example, only the feedback/comments).

## Highlights

- Works with pull requests **and** commits
- Works with public and private repositories
- Selective extraction: choose any of `code`, `feedback`
- Handles paginated GitHub API responses for files and comments
- Configurable ignore rules through `Ignore.txt`
- Configurable extra extraction rules through `SeparateExtractionList.txt`
- Generates a desktop output folder for the selected PR or commit
- Produces diff-style markdown for both main code output and separate extraction files
- Shows markdown document changes as word-level diffs, so a one-word edit in a long paragraph stays readable
- Captures every review verdict and comment, including comments on ignored files

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

| Flag                         | Description                                                                                                         |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| `url` (positional)           | PR or commit URL. Prompted if omitted.                                                                              |
| `-s`, `--sections`, `--only` | Comma-separated: `code`, `feedback`, or `all`. Alias: `comments` = `feedback`. Prompted if omitted (default `all`). |
| `--private` / `--public`     | Skip the private/public prompt.                                                                                     |

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
| `-Sections` / `-Only`  | Comma-separated: `code`, `feedback`, or `all`. Alias: `comments` = `feedback`. Accepts an array (`code,feedback`).                                                                                    |
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

- `Code.md` (section `code`)
- `Feedback.md` (section `feedback`)
- `Reports/Ignore_Report.txt` (only when `code` is requested)
- `Reports/SeparateExtraction_Report.txt` (only when `code` is requested)

Files matched by `SeparateExtractionList.txt` are written to a subfolder named after their
section, mirroring their path in the repository (leading dots are dropped from folder names,
so `.github` becomes `github`):

```text
PR_123_org_repo/
  Code.md
  Feedback.md
  MD/
    README.md.md
    docs/setup.md.md
  Config/
    src/Api/appsettings.json.md
  Dependencies/
    src/Api/MyProject.csproj.md
    web/package.json.md
  CI/
    github/workflows/build.yml.md
  Reports/
    Ignore_Report.txt
    SeparateExtraction_Report.txt
```

Running the parser again for the same PR or commit overwrites files of the same name;
files from an earlier run that are no longer produced stay in the folder.

## Configuration

### Ignore.txt

Controls which files are left out entirely: they are not in `Code.md` and not extracted
separately. It does not filter feedback: review comments on ignored files still appear in
`Feedback.md`.

The starter list ignores lock files, generated code (migrations, `*.Designer.cs`, `*.g.cs`,
snapshots), build output and bundles (`dist/`, `bin/`, `*.min.js`, `*.map`), vendored code
(`node_modules/`, `vendor/`) and binary assets (images, fonts, archives).

Pattern behavior (shared by all three pattern files):

- One glob pattern per line
- Lines starting with `#` are comments
- Optional negation with `!pattern`
- Last matching rule wins
- `*` matches across folders, so `*.md` matches `docs/setup.md` too
- A leading `**/` also matches at the repository root, as in `.gitignore`: `**/*.md` matches `CHANGELOG.md` and `docs/setup.md`

### SeparateExtractionList.txt

Controls which changed files get their own markdown diff file instead of a place in `Code.md`.
A `[Section]` header names the output subfolder for the patterns below it; when several
sections match, the last matching line wins.

```text
[MD]
**/*.md

[Config]
**/appsettings*.json
**/*.yml
```

Starter sections:

- `MD`: markdown documents
- `Config`: appsettings, `*.config`, `.env.example`, YAML, `Dockerfile`, docker-compose files
- `Dependencies`: `package.json`, `*.csproj`, `Directory.*.props`, `requirements*.txt`,
  `pyproject.toml`, `go.mod`, `Cargo.toml`, `pom.xml`, Gradle build files
- `CI`: `.github/workflows/*`, Azure Pipelines and GitLab CI files (listed last, so workflow
  YAML lands here rather than in `Config`)

### Categories.txt

Controls the sections of `Code.md`, with the same `[Section]` syntax: a file goes to the
section of its last matching pattern, and to `Other` when nothing matches. Sections appear in
alphabetical order. The starter file puts `ui/`, `frontend/` and TypeScript/JSX/Vue files under
`Frontend`, and `api/` plus C#/Java/Python/Go files under `Backend` (listed second, so it wins
when both match).

## Output format details

### Code.md and separate extraction files

Code diffs are rendered in markdown code blocks with old/new sections when patch data is available.

Files matched by `SeparateExtractionList.txt` are not included in `Code.md`; they are written only to separate extracted markdown files.

When GitHub does not provide textual patch data for a file (binary files, very large diffs,
renames without changes), the file keeps its heading with a note saying so, both in `Code.md`
and in separate extraction files.

### Markdown files

Markdown documents are prose, so they get a layout of their own:

- A new file is shown as the document itself.
- Each change in a modified file is a `diff` block with one line of context around it
  (context lines are cut at 120 characters):
  - `+` added line, `-` removed line
  - `!` line edited in place, with the edit marked as `[-removed-]{+added+}` and unchanged
    stretches shortened to `…`, so a one-word change in a long paragraph stays visible
- Changes that only touch whitespace (re-padded tables, re-indented lists, re-flowed text) are
  left out and listed in one note with their line numbers.
- An added line identical to the line next to it is flagged as a possible accidental duplicate,
  a common leftover of merge conflicts resolved by keeping both sides.
- A removed file lists its lines as removals.

### Feedback.md

All feedback is captured, whether or not its file matches `Ignore.txt`:

- **Reviews**, first: each reviewer's verdict (Approved / Changes requested / Dismissed) with its
  date and summary. A plain "Commented" review appears only when it has a message.
- **Conversation**: Conversation-tab comments, or for a commit, comments on the commit as a whole.
- **Comments**: inline comment threads, grouped by file in `Code.md` order and sorted by line.
  Each heading names what the comment was left on: `· line 57`, `· lines 50-57`,
  `· whole file`, or `· line 57 (outdated)` once later pushes changed that code. Replies
  follow their comment; a reply whose parent was deleted is kept as its own thread.

Comment text keeps the reviewer's formatting (paragraphs, lists, code blocks). When `code` is
extracted in the same run, a comment on a file that is not in `Code.md` gets a note saying so and
naming the file's separately extracted diff, if there is one.

Code snippets for anchored comments are extracted with this behavior:

- For PR review comments, the code snippet comes from the comment's diff hunk (the code as it
  was when commented), positioned with the comment's original line numbers
- For commit comments (which have no diff hunk), the snippet comes from the file's patch using
  the comment's diff position, or its line
- Exact selected range when a multi-line range was selected
- Otherwise the line with surrounding context
- Tail fallback when line metadata is unavailable
- Whole-file comments have no snippet

## Troubleshooting

### 404 Not Found

Common causes:

- private repository without token
- incorrect PR/commit URL
- missing repository access

### Missing files in output

- Check `Reports/Ignore_Report.txt` for ignored files
- Check `Reports/SeparateExtraction_Report.txt` for files matched by `SeparateExtractionList.txt` and where they were written
- Verify patterns in `Ignore.txt` and `SeparateExtractionList.txt`

### Rate limit issues

Unauthenticated GitHub API usage is limited. Set `GITHUB_TOKEN` to increase limits. When the
limit is reached, the parser stops and says when it resets. Each request times out after 30 seconds.

## Repository files

- `GitHubParser.py`: main parser
- `Ignore.txt`: ignore rules
- `SeparateExtractionList.txt`: rules for separately extracted files and their output folders
- `Categories.txt`: rules for the sections of `Code.md`
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
