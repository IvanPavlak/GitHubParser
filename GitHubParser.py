#!/usr/bin/env python3
"""
GitHub Parser
Extracts information from a GitHub pull request or commit and formats it into
structured markdown files.

Supports selective extraction of sections (code, feedback) so you
can, for example, pull only the feedback/comments for a commit.
"""

import os
import re
import getpass
import argparse
import difflib
import requests
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import List, Dict, Any, Optional, Sequence
from fnmatch import fnmatch


# Canonical output sections and friendly aliases.
ALL_SECTIONS = ['code', 'feedback']
SECTION_ALIASES = {
    'comments': 'feedback',
    'comment': 'feedback',
    'feedbacks': 'feedback',
}

# Seconds to wait for GitHub before giving up; without a timeout a stalled
# connection hangs the run forever.
REQUEST_TIMEOUT = 30

# Markdown diff layout (see GitHubParser._format_markdown_changes).
MARKDOWN_CONTEXT_LINES = 1      # unchanged lines shown around each change
MARKDOWN_CONTEXT_WIDTH = 120    # context lines are cut to this many characters
WORD_DIFF_KEEP_WORDS = 6        # unchanged words kept on each side of an in-line edit
WORD_DIFF_MIN_SIMILARITY = 0.5  # less similar replaced lines are shown as '-' and '+'
DUPLICATE_MIN_LENGTH = 20       # shorter added lines are never flagged as duplicates

TOKEN_PATTERN = re.compile(r'\s+|\w+|[^\w\s]')
TABLE_DELIMITER_PATTERN = re.compile(r'^\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?$')

# Review states shown in Feedback.md. A verdict is shown even without a
# message; a plain "Commented" review only when it carries one.
REVIEW_STATE_LABELS = {
    'APPROVED': 'Approved',
    'CHANGES_REQUESTED': 'Changes requested',
    'DISMISSED': 'Dismissed',
    'COMMENTED': 'Commented',
}
REVIEW_VERDICT_STATES = ('APPROVED', 'CHANGES_REQUESTED', 'DISMISSED')


def resolve_sections(raw: Optional[str]) -> List[str]:
    """
    Resolve a raw ``--sections`` value into an ordered list of canonical sections.

    Accepts comma/semicolon/space separated tokens, the special token ``all``,
    and the aliases in :data:`SECTION_ALIASES` (e.g. ``comments`` -> ``feedback``).
    An empty/``None`` value means "all sections".

    Args:
        raw: The raw sections string (e.g. "feedback", "code,feedback", "all").

    Returns:
        Ordered list of canonical section names, deduplicated, following
        :data:`ALL_SECTIONS` order.
    """
    if not raw:
        return list(ALL_SECTIONS)

    tokens = [t.strip().lower() for t in re.split(r'[,;\s]+', raw) if t.strip()]
    if not tokens or 'all' in tokens:
        return list(ALL_SECTIONS)

    requested = set()
    for token in tokens:
        canonical = SECTION_ALIASES.get(token, token)
        if canonical not in ALL_SECTIONS:
            valid = ', '.join(ALL_SECTIONS)
            raise ValueError(
                f"Unknown section '{token}'. Choose from: {valid} "
                f"(alias: comments=feedback)."
            )
        requested.add(canonical)

    # Preserve canonical ordering regardless of the order tokens were given in.
    return [s for s in ALL_SECTIONS if s in requested]


class GitHubParser:
    def __init__(self, token: Optional[str] = None, ignore_path: Optional[str] = None,
                 separate_extraction_list_path: Optional[str] = None,
                 categories_path: Optional[str] = None):
        """
        Initialize the parser with an optional GitHub token.

        Args:
            token: GitHub personal access token. If None, will try to read from GITHUB_TOKEN env var.
            ignore_path: Path to Ignore.txt file. If None, looks in script directory.
            separate_extraction_list_path: Path to SeparateExtractionList.txt file.
                If None, looks in script directory.
            categories_path: Path to Categories.txt file. If None, looks in script directory.
        """
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
        }
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'

        # Load ignore patterns from Ignore.txt
        script_dir = Path(__file__).parent

        if ignore_path is None:
            ignore_path = script_dir / 'Ignore.txt'
        else:
            ignore_path = Path(ignore_path)

        if separate_extraction_list_path is None:
            separate_extraction_list_path = script_dir / 'SeparateExtractionList.txt'
        else:
            separate_extraction_list_path = Path(separate_extraction_list_path)

        if categories_path is None:
            categories_path = script_dir / 'Categories.txt'
        else:
            categories_path = Path(categories_path)

        self.ignore_patterns = self.load_patterns_file(ignore_path, 'Ignore.txt')
        # (group, pattern) pairs; the group names the output subfolder.
        self.separate_extraction_rules = self.load_grouped_patterns_file(
            separate_extraction_list_path, 'SeparateExtractionList.txt', default_group='Other'
        )
        # (category, pattern) pairs deciding the Code.md sections.
        self.category_rules = self.load_grouped_patterns_file(
            categories_path, 'Categories.txt', default_group='Other'
        )

    def load_patterns_file(self, patterns_path: Path, list_name: str) -> List[str]:
        """
        Load glob patterns from a text file.

        Args:
            patterns_path: Path to patterns file
            list_name: Display name used in log messages

        Returns:
            List of ignore patterns
        """
        patterns = []

        if not patterns_path.exists():
            print(f"Warning: {list_name} not found at {patterns_path}")
            print(f"Using empty pattern list. Create {list_name} to configure patterns.")
            return patterns

        try:
            with open(patterns_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        patterns.append(line)

            print(f"Loaded {len(patterns)} pattern(s) from {list_name}")
        except Exception as e:
            print(f"Error reading {list_name}: {e}")
            print("Continuing with empty pattern list.")

        return patterns

    def load_grouped_patterns_file(self, patterns_path: Path, list_name: str,
                                   default_group: str) -> List[tuple]:
        """
        Load glob patterns grouped under [Section] headers.

        A line like ``[Config]`` starts a group; the patterns below it belong
        to that group until the next header. Patterns before any header belong
        to ``default_group``.

        Args:
            patterns_path: Path to patterns file
            list_name: Display name used in log messages
            default_group: Group for patterns that precede every header

        Returns:
            List of (group, pattern) tuples in file order
        """
        rules = []
        if not patterns_path.exists():
            print(f"Warning: {list_name} not found at {patterns_path}")
            print(f"Using empty pattern list. Create {list_name} to configure patterns.")
            return rules

        group = default_group
        try:
            with open(patterns_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    header = re.fullmatch(r'\[(.+)\]', line)
                    if header:
                        group = header.group(1).strip()
                    else:
                        rules.append((group, line))
            print(f"Loaded {len(rules)} pattern(s) from {list_name}")
        except Exception as e:
            print(f"Error reading {list_name}: {e}")
            print("Continuing with empty pattern list.")
        return rules

    def match_group(self, filepath: str, rules: List[tuple]) -> Optional[str]:
        """
        Find the group of the last (group, pattern) rule matching a path, with
        the same pattern syntax as :meth:`matches_patterns`. A matching
        '!pattern' clears the match. Returns None when nothing matches.
        """
        matched = None
        for group, pattern in rules:
            is_negation = pattern.startswith('!')
            if self.matches_patterns(filepath, [pattern[1:] if is_negation else pattern]):
                matched = None if is_negation else group
        return matched

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Use forward slashes and drop a leading './' (a prefix, not a set of characters)."""
        path = path.replace('\\', '/')
        while path.startswith('./'):
            path = path[2:]
        return path

    def matches_patterns(self, filepath: str, patterns: List[str]) -> bool:
        """
        Match a filepath against an ordered list of glob patterns.

        Supports optional negation via leading '!'.
        Last matching pattern wins.

        '*' matches across folders (fnmatch semantics). As in .gitignore, a
        leading '**/' also matches at the repository root, so '**/*.md'
        matches 'CHANGELOG.md' as well as 'docs/setup.md'.
        """
        normalized_filepath = self._normalize_path(filepath)
        matched = False

        for pattern in patterns:
            is_negation = pattern.startswith('!')
            actual_pattern = self._normalize_path(pattern[1:] if is_negation else pattern)

            candidates = [actual_pattern]
            if actual_pattern.startswith('**/'):
                candidates.append(actual_pattern[3:])

            if any(fnmatch(normalized_filepath, candidate) for candidate in candidates):
                matched = not is_negation

        return matched

    def parse_url(self, url: str) -> Dict[str, str]:
        """
        Parse a GitHub pull request or commit URL.

        Supports:
            - Pull requests: https://github.com/owner/repo/pull/123
            - Commits:       https://github.com/owner/repo/commit/<sha>

        Any trailing fragment (e.g. ``#diff-<hash>`` pointing at a specific
        file) or query string is ignored.

        Args:
            url: GitHub PR or commit URL

        Returns:
            Dict with keys: owner, repo, kind ('pull' | 'commit'), identifier
        """
        pr_match = re.search(r'github\.com/([^/]+)/([^/]+)/pull/(\d+)', url)
        if pr_match:
            owner, repo, number = pr_match.groups()
            return {'owner': owner, 'repo': repo, 'kind': 'pull', 'identifier': number}

        commit_match = re.search(
            r'github\.com/([^/]+)/([^/]+)/commit/([0-9a-fA-F]{7,40})', url
        )
        if commit_match:
            owner, repo, sha = commit_match.groups()
            return {'owner': owner, 'repo': repo, 'kind': 'commit', 'identifier': sha}

        raise ValueError(
            f"Unrecognized GitHub URL: {url}\n"
            f"Expected a pull request URL (.../pull/123) or a commit URL "
            f"(.../commit/<sha>)."
        )

    def should_ignore(self, filepath: str) -> bool:
        """
        Check if a file should be ignored based on ignore patterns.

        Args:
            filepath: Path to the file

        Returns:
            True if file should be ignored, False otherwise
        """
        return self.matches_patterns(filepath, self.ignore_patterns)

    def extraction_group(self, filepath: str) -> Optional[str]:
        """
        Output subfolder for a separately extracted file (the [Section] of its
        last matching rule in SeparateExtractionList.txt), or None. Ignored
        files are never extracted.
        """
        if self.should_ignore(filepath):
            return None
        return self.match_group(filepath, self.separate_extraction_rules)

    def should_extract_separately(self, filepath: str) -> bool:
        """Check if a file should be separately extracted based on patterns."""
        return self.extraction_group(filepath) is not None

    def categorize_file(self, filepath: str) -> str:
        """
        Categorize a file for Code.md using Categories.txt: the [Section] of
        the last matching pattern, or 'Other' when none matches.

        Args:
            filepath: Path to the file

        Returns:
            Category name
        """
        return self.match_group(filepath, self.category_rules) or 'Other'

    def get_file_extension(self, filepath: str) -> str:
        """Get the code block extension for markdown."""
        ext_map = {
            '.cs': 'cs',
            '.js': 'js',
            '.ts': 'ts',
            '.tsx': 'tsx',
            '.jsx': 'jsx',
            '.py': 'py',
            '.java': 'java',
            '.go': 'go',
            '.html': 'html',
            '.css': 'css',
            '.json': 'json',
            '.yml': 'yml',
            '.yaml': 'yaml',
            '.md': 'md',
        }
        ext = os.path.splitext(filepath)[1]
        return ext_map.get(ext, '')

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> requests.Response:
        """
        GET a GitHub API URL with a timeout, turning a rate-limit refusal into
        a readable error instead of a bare HTTPError.

        Args:
            url: The API endpoint URL
            params: Optional query parameters

        Returns:
            The response; its status is left for the caller to check, so a
            404 can still get its own message.
        """
        response = requests.get(url, headers=self.headers, params=params, timeout=REQUEST_TIMEOUT)

        if response.status_code in (403, 429):
            if response.headers.get('X-RateLimit-Remaining') == '0':
                reset = response.headers.get('X-RateLimit-Reset', '')
                when = (f"at {datetime.fromtimestamp(int(reset)):%H:%M}" if reset.isdigit()
                        else "within the hour")
                hint = '' if self.token else (
                    " Set GITHUB_TOKEN to raise the limit from 60 to 5,000 requests per hour."
                )
                raise RuntimeError(f"GitHub API rate limit reached; it resets {when}.{hint}")
            if 'Retry-After' in response.headers:
                raise RuntimeError(
                    f"GitHub API secondary rate limit reached; retry in "
                    f"{response.headers['Retry-After']} seconds."
                )

        return response

    def fetch_paginated(self, url: str, resource_name: str) -> List[Dict[str, Any]]:
        """
        Fetch all pages of a paginated GitHub API endpoint that returns a JSON array.

        Args:
            url: The API endpoint URL
            resource_name: Name of the resource (for progress messages)

        Returns:
            List of all items from all pages
        """
        all_items = []
        page = 1
        per_page = 100  # Maximum allowed by GitHub API

        while True:
            params = {'per_page': per_page, 'page': page}
            response = self._get(url, params=params)
            response.raise_for_status()

            items = response.json()
            if not items:  # No more items
                break

            all_items.extend(items)
            print(f"  Fetched page {page} ({len(items)} {resource_name}, total: {len(all_items)})")

            # Check if there are more pages
            if len(items) < per_page:
                break

            page += 1

        return all_items

    def _handle_not_found(self, kind: str):
        """Raise a helpful error message for a 404 based on auth state."""
        subject = 'PR' if kind == 'pull' else 'commit'
        if self.token:
            raise ValueError(
                f"{subject} not found or you don't have access to it.\n"
                f"Please verify:\n"
                f"  1. The URL is correct\n"
                f"  2. Your GitHub token has the correct permissions (repo scope for private repos)\n"
                f"  3. The repository and {subject} exist"
            )
        raise ValueError(
            f"{subject} not found. This could mean:\n"
            f"  1. The repository is private and requires authentication\n"
            f"  2. The URL is incorrect\n"
            f"  3. The repository or {subject} doesn't exist\n\n"
            f"To access private repositories, set the GITHUB_TOKEN environment variable:\n"
            f"  Windows (PowerShell): $env:GITHUB_TOKEN = 'your_token_here'\n"
            f"  Windows (CMD): set GITHUB_TOKEN=your_token_here\n\n"
            f"Create a token at: https://github.com/settings/tokens"
        )

    def fetch_data(self, parsed: Dict[str, str]) -> Dict[str, Any]:
        """
        Fetch data for a parsed pull request or commit URL.

        Args:
            parsed: Result of :meth:`parse_url`

        Returns:
            Unified dict: {kind, owner, repo, identifier, meta, files,
            comments (anchored to a file), conversation (not anchored), reviews}
        """
        if parsed['kind'] == 'pull':
            return self.fetch_pull_data(
                parsed['owner'], parsed['repo'], parsed['identifier']
            )
        return self.fetch_commit_data(
            parsed['owner'], parsed['repo'], parsed['identifier']
        )

    def fetch_pull_data(self, owner: str, repo: str, pr_number: str) -> Dict[str, Any]:
        """
        Fetch PR data from GitHub API with pagination support.

        Captures every kind of PR comment so feedback is not limited to inline
        code notes:
          * inline review comments  (/pulls/{n}/comments)  – anchored to a diff line
          * conversation comments   (/issues/{n}/comments) – general timeline, no code
          * reviews                 (/pulls/{n}/reviews)    – the Approve/Comment/Request-changes
                                                              verdict and its optional summary

        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number

        Returns:
            Unified data dict for the pull request
        """
        base_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}'
        issue_url = f'https://api.github.com/repos/{owner}/{repo}/issues/{pr_number}'

        print(f"Fetching PR data from {base_url}...")

        # Fetch PR details
        pr_response = self._get(base_url)
        if pr_response.status_code == 404:
            self._handle_not_found('pull')
        pr_response.raise_for_status()
        pr_data = pr_response.json()

        # Fetch files changed (with pagination)
        print("\nFetching changed files...")
        files_data = self.fetch_paginated(f'{base_url}/files', 'files')

        # A PR carries three separate comment streams. They stay apart so
        # Feedback.md can show review verdicts (including approvals that come
        # without a message) separately from the comments.
        print("\nFetching inline review comments...")
        review_comments = self.fetch_paginated(f'{base_url}/comments', 'comments')

        print("\nFetching conversation comments...")
        issue_comments = self.fetch_paginated(f'{issue_url}/comments', 'comments')

        print("\nFetching reviews...")
        reviews = self.fetch_paginated(f'{base_url}/reviews', 'reviews')

        return {
            'kind': 'pull',
            'owner': owner,
            'repo': repo,
            'identifier': pr_number,
            'meta': pr_data,
            'files': files_data,
            'comments': review_comments,
            'conversation': issue_comments,
            'reviews': reviews,
        }

    def fetch_commit_data(self, owner: str, repo: str, sha: str) -> Dict[str, Any]:
        """
        Fetch commit data from GitHub API with pagination support.

        The commit endpoint returns the commit object with an embedded ``files``
        array. Large commits paginate the files across pages of the same object,
        so we walk pages until the files run out.

        Args:
            owner: Repository owner
            repo: Repository name
            sha: Commit SHA

        Returns:
            Unified data dict for the commit
        """
        base_url = f'https://api.github.com/repos/{owner}/{repo}/commits/{sha}'

        print(f"Fetching commit data from {base_url}...")

        # Fetch commit details (page 1 carries the metadata + first slice of files)
        commit_response = self._get(base_url, params={'per_page': 100, 'page': 1})
        if commit_response.status_code == 404:
            self._handle_not_found('commit')
        commit_response.raise_for_status()
        commit_data = commit_response.json()

        print("\nCollecting changed files...")
        files_data = list(commit_data.get('files', []) or [])
        print(f"  Fetched page 1 ({len(files_data)} files, total: {len(files_data)})")

        # Continue paginating files for very large commits.
        if len(files_data) == 100:
            page = 2
            while True:
                response = self._get(base_url, params={'per_page': 100, 'page': page})
                response.raise_for_status()
                page_files = response.json().get('files', []) or []
                if not page_files:
                    break
                files_data.extend(page_files)
                print(f"  Fetched page {page} ({len(page_files)} files, total: {len(files_data)})")
                if len(page_files) < 100:
                    break
                page += 1

        # Fetch commit comments (with pagination)
        print("\nFetching commit comments...")
        comments_data = self.fetch_paginated(f'{base_url}/comments', 'comments')

        # A commit comment without a path is about the commit as a whole.
        return {
            'kind': 'commit',
            'owner': owner,
            'repo': repo,
            'identifier': sha,
            'meta': commit_data,
            'files': files_data,
            'comments': [c for c in comments_data if c.get('path')],
            'conversation': [c for c in comments_data if not c.get('path')],
            'reviews': [],
        }

    def format_code_changes(self, file_data: Dict[str, Any]) -> str:
        """
        Format code changes for a single file.

        Args:
            file_data: File change data from GitHub API

        Returns:
            Formatted markdown string
        """
        filepath = file_data['filename']
        extension = self.get_file_extension(filepath)
        status = file_data.get('status', '')
        patch = file_data.get('patch', '')

        # GitHub sends no patch for binary files, very large diffs and renames
        # without changes; keep the file visible with a note instead.
        if not patch:
            return self._format_no_patch(file_data)

        # Markdown is prose, not code: it gets a diff layout of its own.
        if os.path.splitext(filepath)[1].lower() == '.md':
            return self._format_markdown_changes(file_data)

        # Check if file was deleted
        if status == 'removed':
            output = f"### `{filepath}`\n\n"
            output += f"```{extension}\n"
            output += "// Old\n...\n"

            # Extract the old code from the patch
            patch_normalized = patch.replace('\r\n', '\n').replace('\r', '\n')
            lines = patch_normalized.split('\n')
            old_code = []
            for line in lines:
                if not line:
                    continue
                if line.startswith('@@') or line.startswith('+++') or line.startswith('---'):
                    continue
                # For removed files, all lines are either context (space) or removed (-)
                if line and line[0] in [' ', '-']:
                    old_code.append(line[1:])

            if old_code:
                output += '\n'.join(old_code)
                output += "\n...\n"

            output += "\n// New\n...\n"
            output += "FILE REMOVED\n"
            output += "...\n"
            output += "```\n\n"
            return output

        # Parse the patch to extract old and new code sections
        # Normalize line endings (handle both \r\n and \n)
        patch = patch.replace('\r\n', '\n').replace('\r', '\n')
        lines = patch.split('\n')
        old_sections = []
        new_sections = []
        current_old = []
        current_new = []

        for line in lines:
            # Skip empty lines that aren't part of the actual code
            if not line:
                continue

            if line.startswith('@@'):
                # New hunk, save previous sections if any
                if current_old or current_new:
                    if current_old:
                        old_sections.append('\n'.join(current_old))
                    if current_new:
                        new_sections.append('\n'.join(current_new))
                    current_old = []
                    current_new = []
            elif line.startswith('-') and not line.startswith('---'):
                # Removed line - preserve the content after the '-'
                current_old.append(line[1:])
            elif line.startswith('+') and not line.startswith('+++'):
                # Added line - preserve the content after the '+'
                current_new.append(line[1:])
            elif line.startswith(' '):
                # Context line - preserve the content after the space
                current_old.append(line[1:])
                current_new.append(line[1:])

        # Save last section
        if current_old or current_new:
            if current_old:
                old_sections.append('\n'.join(current_old))
            if current_new:
                new_sections.append('\n'.join(current_new))

        # Format output
        output = f"### `{filepath}`\n\n"
        output += f"```{extension}\n"

        # If only additions (new file or new code only)
        if not old_sections and new_sections:
            # Join sections with ... separator
            formatted_sections = []
            for section in new_sections:
                formatted_sections.append(section)
            output += '\n...\n'.join(formatted_sections)
        else:
            # Show old and new sections
            output += "// Old\n...\n"
            # Join old sections with ... separator
            output += '\n...\n'.join(old_sections)
            output += "\n...\n\n// New\n...\n"
            # Join new sections with ... separator
            output += '\n...\n'.join(new_sections)
            output += "\n..."

        output += "\n```\n\n"

        return output

    def _format_no_patch(self, file_data: Dict[str, Any]) -> str:
        """
        Format a file GitHub sent no textual patch for: its header and a note.

        Args:
            file_data: File change data from GitHub API

        Returns:
            Formatted markdown string
        """
        details = [file_data.get('status') or 'changed']
        if file_data.get('previous_filename'):
            details.append(f"from `{file_data['previous_filename']}`")
        additions = file_data.get('additions', 0)
        deletions = file_data.get('deletions', 0)
        if additions or deletions:
            details.append(f"+{additions:,} -{deletions:,}")

        return (
            f"### `{file_data['filename']}`\n\n"
            f"_No textual diff from GitHub (binary, too large, or renamed without "
            f"changes) · {' · '.join(details)}._\n\n"
        )

    def _format_markdown_changes(self, file_data: Dict[str, Any]) -> str:
        """
        Format a markdown file's diff for reading.

        A new file is shown as the document itself. Otherwise each change is
        a ```diff block with one line of context around it: '+' added, '-'
        removed, and '!' for a line edited in place, where [-old-]{+new+}
        marks the edited words and '…' stands for unchanged text left out.
        These docs keep a paragraph on one line, so printing an edited line
        twice would bury a one-word change in thousands of characters.
        Changes that only touch whitespace (re-padded tables, re-indented
        lists) are left out and listed in one note, and an added line
        identical to its neighbour is flagged as a possible duplicate.

        Args:
            file_data: File change data from GitHub API, with a patch

        Returns:
            Formatted markdown string
        """
        filepath = file_data['filename']
        status = file_data.get('status', '')
        rows = self._parse_patch_rows(file_data.get('patch', ''))
        output = f"### `{filepath}`\n\n"

        if status == 'added':
            content = '\n'.join(row['text'] for row in rows if row['kind'] == '+').rstrip()
            output += f"_New file · {file_data.get('additions', 0):,} lines, shown as-is below._\n\n"
            return output + "---\n\n" + content + "\n\n---\n"

        if status == 'removed':
            removed = [row['text'].rstrip() for row in rows if row['kind'] == '-']
            fence = self._code_fence(removed)
            output += f"_File removed · {len(removed):,} lines._\n\n"
            return output + f"{fence}diff\n" + ''.join(f"-{text}\n" for text in removed) + f"{fence}\n\n"

        display = self._markdown_display_rows(rows)
        hunks = self._markdown_hunks(display)
        reformatted = [row['new'] for row in display if row['kind'] == 'ws']

        if hunks:
            counts = [(sum(row['kind'] == kind for row in display), label)
                      for kind, label in (('+', 'added'), ('edit', 'edited'), ('-', 'removed'))]
            summary = ' · '.join(f"{count} {label}" for count, label in counts if count)
            output += f"_{len(hunks)} change{'s' if len(hunks) != 1 else ''} · {summary} lines_\n\n"
        else:
            output += "_Only whitespace changed._\n\n"
        if reformatted:
            output += (f"_Whitespace-only re-format hidden ({len(reformatted)} lines): "
                       f"{self._line_ranges(reformatted)}._\n\n")

        for hunk in hunks:
            fence = self._code_fence(row.get(key, '') for row in hunk for key in ('text', 'before', 'after'))
            output += f"#### {self._markdown_hunk_label(hunk)}\n\n{fence}diff\n"
            for row in hunk:
                if row['kind'] == 'edit':
                    output += '!' + self._word_diff(row['before'], row['after']).rstrip() + '\n'
                elif row['kind'] in ('-', '+'):
                    output += row['kind'] + row['text'].rstrip() + '\n'
                else:
                    output += ' ' + self._clip_context(row['text']) + '\n'
            output += f"{fence}\n\n"
            for line, neighbour in self._duplicate_warnings(hunk):
                output += (f"> ⚠ Line {line} is identical to line {neighbour} "
                           f"(possible accidental duplicate).\n\n")

        return output

    def _parse_patch_rows(self, patch: str) -> List[Dict[str, Any]]:
        """
        Parse a unified-diff patch into rows.

        Each row has a 'kind' (' ' context, '-' removed, '+' added, '@' hunk
        break), the old- and new-file line numbers at that point ('old',
        'new') and the line's 'text'. A removed row's 'new' is where the line
        used to sit in the new file, and an added row's 'old' likewise.

        Args:
            patch: A unified-diff patch string

        Returns:
            List of row dicts in patch order
        """
        rows: List[Dict[str, Any]] = []
        old_line = new_line = 1

        for line in patch.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            if line.startswith('@@'):
                header = re.match(r'@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
                old_line, new_line = (int(header.group(1)), int(header.group(2))) if header else (1, 1)
                rows.append({'kind': '@'})
                continue

            # Blank context lines arrive as a single space; a truly empty line
            # is patch padding, and '\' starts "\ No newline at end of file".
            if not line or line.startswith('\\'):
                continue

            kind = line[0] if line[0] in '+-' else ' '
            rows.append({'kind': kind, 'old': old_line, 'new': new_line, 'text': line[1:]})
            if kind != '+':
                old_line += 1
            if kind != '-':
                new_line += 1

        return rows

    def _markdown_display_rows(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Classify the changed lines of a markdown patch for display.

        Within each run of removed/added lines, lines that only changed in
        whitespace become 'ws' rows (shown as context, listed in a note),
        similar replaced lines become 'edit' rows (rendered as a word diff)
        and the rest stay removals and additions.

        Args:
            rows: Rows from _parse_patch_rows

        Returns:
            The rows with every run of changes replaced by its classified rows
        """
        display: List[Dict[str, Any]] = []
        index = 0

        while index < len(rows):
            if rows[index]['kind'] not in ('-', '+'):
                display.append(rows[index])
                index += 1
                continue

            end = index
            while end < len(rows) and rows[end]['kind'] in ('-', '+'):
                end += 1
            removed = [row for row in rows[index:end] if row['kind'] == '-']
            added = [row for row in rows[index:end] if row['kind'] == '+']
            index = end

            # Re-flowed JSON or a re-wrapped paragraph: same text, new line breaks.
            if removed and added and self._same_ignoring_whitespace(removed, added):
                display.extend({**row, 'kind': 'ws'} for row in added)
                continue

            matcher = difflib.SequenceMatcher(
                None,
                [self._normalize_markdown_line(row['text']) for row in removed],
                [self._normalize_markdown_line(row['text']) for row in added],
                autojunk=False,
            )
            for op, i1, i2, j1, j2 in matcher.get_opcodes():
                if op == 'equal':
                    display.extend({**row, 'kind': 'ws'} for row in added[j1:j2])
                elif op == 'delete':
                    display.extend(removed[i1:i2])
                elif op == 'insert':
                    display.extend(added[j1:j2])
                else:
                    for kind, old_row, new_row in self._pair_similar_lines(removed[i1:i2], added[j1:j2]):
                        if kind == 'edit':
                            display.append({
                                'kind': 'edit', 'old': old_row['old'], 'new': new_row['new'],
                                'before': old_row['text'], 'after': new_row['text'],
                            })
                        else:
                            display.append(old_row if kind == '-' else new_row)

        return display

    def _normalize_markdown_line(self, text: str) -> str:
        """
        Whitespace-insensitive form of a markdown line, used to recognise
        changes that only re-pad a table or re-indent a list. Table delimiter
        rows ('|---|:--:|') are reduced to their alignment, because re-padding
        changes how many dashes they have.
        """
        stripped = text.strip()
        if '-' in stripped and '|' in stripped and TABLE_DELIMITER_PATTERN.match(stripped):
            cells = [cell.strip() for cell in stripped.strip('|').split('|')]
            return '|' + '|'.join(
                (':' if cell.startswith(':') else '') + '---'
                + (':' if cell.endswith(':') and len(cell) > 1 else '')
                for cell in cells
            ) + '|'
        return re.sub(r'\s+', ' ', stripped)

    def _same_ignoring_whitespace(self, removed: List[Dict[str, Any]],
                                  added: List[Dict[str, Any]]) -> bool:
        """True when two runs of lines differ only in whitespace, line breaks included."""
        def squash(rows):
            return re.sub(r'\s+', '', ''.join(self._normalize_markdown_line(row['text']) for row in rows))
        return squash(removed) == squash(added)

    def _pair_similar_lines(self, removed: List[Dict[str, Any]],
                            added: List[Dict[str, Any]]) -> List[tuple]:
        """
        Pair replaced lines with their edited versions the way difflib's
        Differ does: take the most similar removed/added pair, then repeat on
        the lines before and after it. A line without a partner that is more
        than WORD_DIFF_MIN_SIMILARITY alike stays a plain removal or addition.

        Args:
            removed: Removed rows of one replacement
            added: Added rows of the same replacement

        Returns:
            ('edit', removed_row, added_row), ('-', removed_row, None) and
            ('+', None, added_row) tuples in file order
        """
        if not removed:
            return [('+', None, row) for row in added]
        if not added:
            return [('-', row, None) for row in removed]

        best, best_i, best_j = WORD_DIFF_MIN_SIMILARITY, -1, -1
        removed_tokens = [TOKEN_PATTERN.findall(row['text']) for row in removed]
        matcher = difflib.SequenceMatcher(autojunk=False)
        for j, added_row in enumerate(added):
            matcher.set_seq2(TOKEN_PATTERN.findall(added_row['text']))
            for i, tokens in enumerate(removed_tokens):
                matcher.set_seq1(tokens)
                if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                    continue
                ratio = matcher.ratio()
                if ratio > best:
                    best, best_i, best_j = ratio, i, j

        if best_i < 0:
            return [('-', row, None) for row in removed] + [('+', None, row) for row in added]
        return (
            self._pair_similar_lines(removed[:best_i], added[:best_j])
            + [('edit', removed[best_i], added[best_j])]
            + self._pair_similar_lines(removed[best_i + 1:], added[best_j + 1:])
        )

    def _word_diff(self, before: str, after: str) -> str:
        """
        Render an edited line as one line with [-removed-]{+added+} markers,
        shortening unchanged stretches to the words around each change.

        Args:
            before: The line as it was
            after: The line as it is now

        Returns:
            The marked-up line
        """
        old_tokens = TOKEN_PATTERN.findall(before)
        new_tokens = TOKEN_PATTERN.findall(after)
        matcher = difflib.SequenceMatcher(None, old_tokens, new_tokens, autojunk=False)
        segments = [
            [op, ''.join(old_tokens[i1:i2]), ''.join(new_tokens[j1:j2])]
            for op, i1, i2, j1, j2 in matcher.get_opcodes()
        ]

        # Fold a tiny unchanged island (a space, a single word) between two
        # changes into them, so the result reads as phrases, not confetti.
        index = 1
        while index < len(segments) - 1:
            segment = segments[index]
            if (segment[0] == 'equal'
                    and segments[index - 1][0] != 'equal' and segments[index + 1][0] != 'equal'
                    and len([t for t in TOKEN_PATTERN.findall(segment[1]) if not t.isspace()]) <= 1):
                previous, following = segments[index - 1], segments[index + 1]
                segments[index - 1:index + 2] = [[
                    'replace',
                    previous[1] + segment[1] + following[1],
                    previous[2] + segment[2] + following[2],
                ]]
            else:
                index += 1

        output = []
        last = len(segments) - 1
        for index, (op, old, new) in enumerate(segments):
            if op == 'equal':
                if last == 0:
                    output.append(old)
                else:
                    output.append(self._trim_unchanged(
                        old, 'end' if index == 0 else 'start' if index == last else 'both'))
                continue

            # A change of spacing alone is noise next to real edits.
            if not old.strip() and not new.strip():
                output.append(new)
                continue

            # Whitespace shared by both sides stays outside the markers:
            # "{+word+} " rather than "{+word +}".
            sides = [text for text in (old, new) if text]
            lead = os.path.commonprefix([re.match(r'\s*', text).group(0) for text in sides])
            trail = os.path.commonprefix(
                [re.search(r'\s*$', text[len(lead):]).group(0)[::-1] for text in sides]
            )[::-1]
            old_core = old[len(lead):len(old) - len(trail)] if old else ''
            new_core = new[len(lead):len(new) - len(trail)] if new else ''
            output.append(
                lead
                + (f"[-{old_core}-]" if old_core else '')
                + (f"{{+{new_core}+}}" if new_core else '')
                + trail
            )

        return ''.join(output)

    def _trim_unchanged(self, text: str, keep: str) -> str:
        """
        Shorten an unchanged stretch of an edited line to the words next to
        the change: keep='end' for a stretch that starts the line, 'start'
        for one that ends it, and 'both' for one between two changes.
        """
        tokens = TOKEN_PATTERN.findall(text)
        words = [i for i, token in enumerate(tokens) if re.match(r'\w', token)]
        count = WORD_DIFF_KEEP_WORDS

        if keep == 'end':
            if len(words) <= count:
                return text
            return '… ' + ''.join(tokens[words[-count]:]).lstrip()
        if keep == 'start':
            if len(words) <= count:
                return text
            return ''.join(tokens[:words[count - 1] + 1]).rstrip() + ' …'
        if len(words) <= 2 * count:
            return text
        return (''.join(tokens[:words[count - 1] + 1]).rstrip() + ' … '
                + ''.join(tokens[words[-count]:]).lstrip())

    def _markdown_hunks(self, rows: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """
        Group display rows into hunks: each change with MARKDOWN_CONTEXT_LINES
        unchanged rows on either side, merging changes whose context touches.
        """
        windows: List[List[int]] = []
        for index, row in enumerate(rows):
            if row['kind'] not in ('-', '+', 'edit'):
                continue
            low = high = index
            for _ in range(MARKDOWN_CONTEXT_LINES):
                if low > 0 and rows[low - 1]['kind'] in (' ', 'ws'):
                    low -= 1
                if high + 1 < len(rows) and rows[high + 1]['kind'] in (' ', 'ws'):
                    high += 1
            if windows and low <= windows[-1][1] + 1:
                windows[-1][1] = max(windows[-1][1], high)
            else:
                windows.append([low, high])
        return [rows[low:high + 1] for low, high in windows]

    def _markdown_hunk_label(self, hunk: List[Dict[str, Any]]) -> str:
        """Heading for a hunk: the new-file lines it adds or edits, else the old lines it removes."""
        new_lines = [row['new'] for row in hunk if row['kind'] in ('+', 'edit')]
        if new_lines:
            first, last = min(new_lines), max(new_lines)
            return f"Line {first}" if first == last else f"Lines {first}–{last}"
        old_lines = [row['old'] for row in hunk if row['kind'] == '-']
        first, last = min(old_lines), max(old_lines)
        return f"Removed old line {first}" if first == last else f"Removed old lines {first}–{last}"

    def _duplicate_warnings(self, hunk: List[Dict[str, Any]]) -> List[tuple]:
        """
        Find added lines identical to the line right above or below them in
        the new file, usually an accident such as a merge that kept both sides.

        Returns:
            (added line number, identical neighbour's line number) tuples
        """
        new_side = [row for row in hunk if row['kind'] in (' ', 'ws', '+', 'edit')]
        warnings = []
        for index, row in enumerate(new_side):
            if row['kind'] != '+' or len(row['text'].strip()) < DUPLICATE_MIN_LENGTH:
                continue
            text = self._normalize_markdown_line(row['text'])
            for neighbour in (index - 1, index + 1):
                if 0 <= neighbour < len(new_side):
                    other = new_side[neighbour]
                    other_text = other['after'] if other['kind'] == 'edit' else other['text']
                    if self._normalize_markdown_line(other_text) == text:
                        warnings.append((row['new'], other['new']))
                        break
        return warnings

    def _clip_context(self, text: str) -> str:
        """Cut a context line to MARKDOWN_CONTEXT_WIDTH characters; it only shows where a change sits."""
        text = text.rstrip()
        if len(text) <= MARKDOWN_CONTEXT_WIDTH:
            return text
        return text[:MARKDOWN_CONTEXT_WIDTH - 2].rstrip() + ' …'

    @staticmethod
    def _code_fence(texts) -> str:
        """A backtick fence longer than any fence inside the fenced lines (docs embed ``` blocks)."""
        longest = 2
        for text in texts:
            run = re.match(r'\s*(`{3,})', text)
            if run:
                longest = max(longest, len(run.group(1)))
        return '`' * (longest + 1)

    @staticmethod
    def _line_ranges(numbers: List[int]) -> str:
        """Compress line numbers into ranges: [8, 9, 10, 13] -> '8–10, 13'."""
        ranges: List[List[int]] = []
        for number in sorted(set(numbers)):
            if ranges and number == ranges[-1][1] + 1:
                ranges[-1][1] = number
            else:
                ranges.append([number, number])
        return ', '.join(f"{first}" if first == last else f"{first}–{last}" for first, last in ranges)

    def _build_new_line_map(self, patch: str) -> List[tuple]:
        """
        Parse a unified-diff patch into a list of (new_line_number, code_text) tuples
        representing every line that exists in the new version of the file.

        Args:
            patch: A unified-diff patch string (full file patch or diff_hunk)

        Returns:
            Sorted list of (line_number, code_text) tuples for the new-file side
        """
        if not patch:
            return []

        patch = patch.replace('\r\n', '\n').replace('\r', '\n')
        lines = patch.split('\n')

        new_line_map = []
        current_new_line = 0

        for line in lines:
            if not line:
                continue
            if line.startswith('@@'):
                match = re.match(r'@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@', line)
                if match:
                    current_new_line = int(match.group(1))
                continue
            if line.startswith('---') or line.startswith('+++'):
                continue
            if line.startswith('-'):
                # Removed line – not in new file
                continue
            if line.startswith('+') or line.startswith(' '):
                new_line_map.append((current_new_line, line[1:]))
                current_new_line += 1

        return new_line_map

    def _extract_lines_with_context(self, full_patch: str, anchor_line: int,
                                    context: int = 5) -> List[str]:
        """
        Extract *anchor_line* together with up to *context* lines before and
        after it from the new-file side of a patch.

        Args:
            full_patch: The complete file patch
            anchor_line: The line number to centre the window on
            context: Number of lines to include above and below (default: 5)

        Returns:
            List of code lines in the context window
        """
        line_map = self._build_new_line_map(full_patch)
        if not line_map:
            return []

        # Find the position of anchor_line in the map
        anchor_idx = None
        for idx, (num, _) in enumerate(line_map):
            if num == anchor_line:
                anchor_idx = idx
                break

        if anchor_idx is None:
            # Anchor not found – fall back to closest available line
            closest = min(range(len(line_map)),
                          key=lambda i: abs(line_map[i][0] - anchor_line),
                          default=None)
            if closest is None:
                return []
            anchor_idx = closest

        lo = max(0, anchor_idx - context)
        hi = min(len(line_map), anchor_idx + context + 1)
        return [code for _, code in line_map[lo:hi]]

    def extract_comment_context(self, diff_hunk: str,
                                comment_line: int = None,
                                start_line: int = None) -> List[str]:
        """
        Extract the code snippet a reviewer commented on.

        Always sources code from the diff_hunk, which preserves exactly the
        code that was present when the comment was placed — even if the file
        has since changed (outdated comments).

        **Exact-range mode** – When the reviewer selected a clear range of
        lines (GitHub supplies both *start_line* and *comment_line*), return
        exactly those lines from the diff_hunk.

        **Fallback context mode** – When only a single anchor line is known,
        return the anchor line with up to 5 lines of context above and below
        it (limited to what the diff_hunk contains).

        **Last-resort mode** – If line numbers are unavailable (e.g. very old
        comments), show the tail of the diff_hunk with up to 5 lines of context.

        Args:
            diff_hunk: The diff hunk ending at the commented line (comment-time snapshot)
            comment_line: Line number in the new file at the commented commit
                (GitHub 'original_line', which matches the diff_hunk)
            start_line: First line of a multi-line selection (GitHub 'original_start_line')

        Returns:
            List of code lines representing the relevant snippet
        """
        if not diff_hunk:
            return []

        # Build a line map from the diff_hunk itself so we always use the
        # code as it was when the comment was placed.
        line_map = self._build_new_line_map(diff_hunk)

        if not line_map:
            return []

        # --- Exact-range mode ---------------------------------------------------
        # Reviewer selected a clear range of lines (start_line .. comment_line).
        if start_line and comment_line:
            result = [code for num, code in line_map
                      if start_line <= num <= comment_line]
            if result:
                return result

        # --- Fallback context mode (anchor ±5) -----------------------------------
        # Single anchor line — show it with up to 5 lines above and below.
        anchor = comment_line or 0
        if anchor:
            anchor_idx = None
            for idx, (num, _) in enumerate(line_map):
                if num == anchor:
                    anchor_idx = idx
                    break

            if anchor_idx is not None:
                lo = max(0, anchor_idx - 5)
                hi = min(len(line_map), anchor_idx + 5 + 1)
                return [code for _, code in line_map[lo:hi]]

        # --- Last-resort mode ---------------------------------------------------
        # No usable line numbers — show the tail of the hunk (the commented
        # line is always the last line GitHub includes in the hunk).
        all_lines = [code for _, code in line_map]
        start_idx = max(0, len(all_lines) - 11)
        return all_lines[start_idx:]

    def _extract_context_by_position(self, patch: str, position: int,
                                     context: int = 5) -> List[str]:
        """
        Extract a window of new-file code around a GitHub diff *position*.

        Commit comments (unlike PR review comments) carry no diff_hunk and are
        anchored by ``position`` — the 1-based index of the commented line within
        the file's unified diff, counting every line after the first ``@@`` hunk
        header (later ``@@`` headers included). This maps that position back to
        the surrounding code on the new-file side.

        Args:
            patch: The file's unified-diff patch (as returned by the GitHub API).
            position: The comment's diff position (GitHub 'position' field).
            context: Number of visible lines to include above and below the anchor.

        Returns:
            List of code lines around the anchored position (removed lines and
            hunk headers are omitted from the rendered snippet).
        """
        if not patch or not position:
            return []

        patch = patch.replace('\r\n', '\n').replace('\r', '\n')
        lines = patch.split('\n')

        # Walk the diff, tracking each line's GitHub position. Positions start at
        # 1 on the first line after the first hunk header and increment for every
        # subsequent line (removed lines and later '@@' headers included).
        visible = []  # (position, code_text) for lines present on the new-file side
        pos = 0
        seen_hunk = False
        for line in lines:
            if not seen_hunk:
                if line.startswith('@@'):
                    seen_hunk = True
                continue
            pos += 1
            if line.startswith('+') and not line.startswith('+++'):
                visible.append((pos, line[1:]))
            elif line.startswith(' '):
                visible.append((pos, line[1:]))
            # Removed ('-') lines and later '@@' headers consume a position but
            # are not part of the new-file snippet, so they are skipped here.

        if not visible:
            return []

        # Anchor on the exact position if it is a visible line; otherwise fall
        # back to the closest visible line (e.g. a comment on a removed line).
        anchor_idx = next((i for i, (p, _) in enumerate(visible) if p == position), None)
        if anchor_idx is None:
            anchor_idx = min(range(len(visible)),
                             key=lambda i: abs(visible[i][0] - position))

        lo = max(0, anchor_idx - context)
        hi = min(len(visible), anchor_idx + context + 1)
        return [code for _, code in visible[lo:hi]]

    def _line_for_position(self, patch: str, position: int) -> Optional[int]:
        """
        Map a GitHub diff position (counted as in _extract_context_by_position)
        to the new-file line it points at.

        Args:
            patch: The file's unified-diff patch
            position: The comment's diff position

        Returns:
            The new-file line number, or None when the position lands on a
            removed line or a hunk header, or lies outside the patch
        """
        new_line = 0
        pos = 0
        seen_hunk = False
        for line in patch.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            header = re.match(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line)
            if not seen_hunk:
                if header:
                    seen_hunk = True
                    new_line = int(header.group(1))
                continue
            pos += 1
            if header:
                new_line = int(header.group(1))
            elif line.startswith('+') or line.startswith(' '):
                if pos == position:
                    return new_line
                new_line += 1
            if pos >= position:
                return None
        return None

    def _build_code_md(self, files_by_category: Dict[str, List[Dict[str, Any]]]) -> str:
        """Build the Code.md content from categorized files."""
        code_md = "# Code\n\n"
        for category in sorted(files_by_category.keys()):
            code_md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                code_md += self.format_code_changes(file_data)
        return code_md

    def _build_feedback_md(self, data: Dict[str, Any], files_by_path: Dict[str, Dict[str, Any]],
                           separate_names: Dict[str, str], with_code: bool) -> str:
        """
        Build the Feedback.md content.

        Every review, conversation comment and inline comment is included,
        whether or not its file matches Ignore.txt: the ignore list decides
        what goes into Code.md, not which feedback is worth reading.

        Review verdicts and their summaries come first, then conversation
        comments, then inline comment threads grouped by file in Code.md
        order and sorted by line.

        Args:
            data: Unified data dict from :meth:`fetch_data`
            files_by_path: Every changed file, keyed by path
            separate_names: Output file name of each separately extracted file
            with_code: True when Code.md and the separate files are written in
                the same run, so comments can say where their file's diff is

        Returns:
            Feedback.md content
        """
        blocks = []

        reviews = [
            review for review in data.get('reviews', [])
            if review.get('state') in REVIEW_VERDICT_STATES
            or (review.get('state') == 'COMMENTED' and (review.get('body') or '').strip())
        ]
        if reviews:
            block = "## Reviews\n\n"
            for review in reviews:
                label = REVIEW_STATE_LABELS.get(review['state'], review['state'])
                date = (review.get('submitted_at') or '')[:10]
                body = (review.get('body') or '').strip()
                block += f"- `{self._author(review)}` · **{label}**" + (f" · {date}" if date else '')
                block += (f" →{self._format_comment_body(body)}" if body else '') + "\n\n"
            blocks.append(block)

        if data.get('conversation'):
            block = "## Conversation\n\n"
            for comment in data['conversation']:
                date = (comment.get('created_at') or '')[:10]
                block += (f"- `{self._author(comment)}`" + (f" · {date}" if date else '')
                          + f" →{self._format_comment_body(comment.get('body'))}\n\n")
            blocks.append(block)

        if data.get('comments'):
            blocks.append("## Comments\n\n" + self._format_comment_threads(
                data['comments'], files_by_path, separate_names, with_code))

        return "# Feedback\n\n" + (''.join(blocks) if blocks else "No comments found.\n")

    def _format_comment_threads(self, comments: List[Dict[str, Any]],
                                files_by_path: Dict[str, Dict[str, Any]],
                                separate_names: Dict[str, str], with_code: bool) -> str:
        """
        Format inline comments as threads, each under a header naming its file
        and what the comment was left on, followed by that code.

        Args:
            comments: Comments anchored to a file
            files_by_path: Every changed file, keyed by path
            separate_names: Output file name of each separately extracted file
            with_code: True when Code.md and the separate files are written too

        Returns:
            Markdown for the threads
        """
        ids = {comment.get('id') for comment in comments if comment.get('id') is not None}
        replies: Dict[Any, List[Dict[str, Any]]] = {}
        roots = []
        for comment in comments:
            parent = comment.get('in_reply_to_id')
            # A reply whose parent was deleted becomes a thread of its own
            # instead of disappearing.
            if parent is not None and parent in ids:
                replies.setdefault(parent, []).append(comment)
            else:
                roots.append(comment)

        # Same order as Code.md: category, then the order GitHub lists the files in.
        file_order = {path: index for index, path in enumerate(files_by_path)}

        def thread_order(root):
            path = root.get('path') or ''
            line = root.get('line') or root.get('original_line') or root.get('position') or 0
            return (self.categorize_file(path), file_order.get(path, len(file_order)), path,
                    line, root.get('created_at') or '')

        def thread_of(root):
            thread, pending = [], list(replies.get(root.get('id'), []))
            while pending:
                reply = pending.pop()
                thread.append(reply)
                pending.extend(replies.get(reply.get('id'), []))
            return [root] + sorted(thread, key=lambda reply: reply.get('created_at') or '')

        output = ''
        noted_paths = set()
        for root in sorted(roots, key=thread_order):
            path = root.get('path') or ''
            file_data = files_by_path.get(path)
            patch = file_data.get('patch', '') if file_data else ''

            target = self._describe_comment_target(root, patch)
            output += f"### `{path}`" + (f" · {target}" if target else '') + "\n\n"

            if with_code and path not in noted_paths:
                note = self._feedback_location_note(path, files_by_path, separate_names)
                if note:
                    output += f"_{note}_\n\n"
            noted_paths.add(path)

            snippet = self._comment_snippet(root, patch)
            if snippet:
                fence = self._code_fence(snippet)
                output += f"{fence}{self.get_file_extension(path)}\n" + '\n'.join(snippet) + f"\n{fence}\n\n"

            for comment in thread_of(root):
                output += f"- `{self._author(comment)}` →{self._format_comment_body(comment.get('body'))}\n\n"

        return output

    def _describe_comment_target(self, comment: Dict[str, Any], patch: str) -> str:
        """
        Describe what an inline comment was left on, for its header: 'line 57',
        'lines 50–57', 'whole file', or 'line 57 (outdated)' once later pushes
        changed the code it was left on.
        """
        if comment.get('subject_type') == 'file':
            return 'whole file'

        if comment.get('line'):
            start, end, outdated = comment.get('start_line'), comment['line'], False
        elif comment.get('original_line'):
            start, end, outdated = comment.get('original_start_line'), comment['original_line'], True
        elif comment.get('position') and patch:
            # Commit comment: anchored by diff position; its 'line' is often absent.
            start, end, outdated = None, self._line_for_position(patch, comment['position']), False
        else:
            return ''

        if not end:
            return ''
        target = f"lines {start}–{end}" if start and start != end else f"line {end}"
        return target + (' (outdated)' if outdated else '')

    def _comment_snippet(self, comment: Dict[str, Any], patch: str) -> List[str]:
        """
        The code an inline comment refers to; none for a whole-file comment,
        whose empty diff_hunk would otherwise pull in the top of the file.

        A PR review comment's diff_hunk preserves the code as it was when the
        comment was placed, outdated comments included. A commit comment has
        no diff_hunk and is anchored by its diff position in the file's patch.
        """
        if comment.get('subject_type') == 'file':
            return []

        if comment.get('diff_hunk'):
            # The hunk is frozen at the commit the comment was left on, so it
            # is positioned with that commit's line numbers, not with 'line',
            # which follows the latest push.
            if comment.get('original_line'):
                anchor, start = comment['original_line'], comment.get('original_start_line')
            else:
                anchor, start = comment.get('line') or 0, comment.get('start_line')
            return self.extract_comment_context(comment['diff_hunk'], comment_line=anchor, start_line=start)

        if not patch:
            return []
        if comment.get('position'):
            return self._extract_context_by_position(patch, comment['position'])
        if comment.get('line'):
            return self._extract_lines_with_context(patch, comment['line'])
        return []

    def _feedback_location_note(self, path: str, files_by_path: Dict[str, Dict[str, Any]],
                                separate_names: Dict[str, str]) -> str:
        """Say where a commented file's diff is when it is not in Code.md."""
        if path not in files_by_path:
            return "File is no longer part of this diff"
        ignored = self.should_ignore(path)
        separate = separate_names.get(path)
        if not ignored and not separate:
            return ''
        note = "Not in Code.md (matches Ignore.txt)" if ignored else "Not in Code.md"
        return note + (f"; full diff in `{separate}`" if separate else '')

    @staticmethod
    def _author(item: Dict[str, Any]) -> str:
        """Login of a comment's or review's author."""
        return (item.get('user') or {}).get('login', 'unknown')

    @staticmethod
    def _format_comment_body(body: Optional[str]) -> str:
        """
        Format a comment body to follow 'author →' in a bullet.

        A one-line body stays on the bullet's line. A longer one starts on the
        next paragraph, indented as the bullet's continuation, so blank lines,
        lists and code blocks survive as the reviewer wrote them.
        """
        text = (body or '').replace('\r\n', '\n').strip()
        if '\n' not in text:
            return f" {text}" if text else ''
        return '\n\n' + '\n'.join(f"  {line}" if line.strip() else '' for line in text.split('\n'))

    def generate_markdown_sections(self, data: Dict[str, Any],
                                   sections: Optional[Sequence[str]] = None) -> Dict[str, Any]:
        """
        Generate the requested markdown sections.

        Args:
            data: Unified data dict from :meth:`fetch_data`
            sections: Which sections to generate. Any subset of
                ``code``, ``feedback``. Defaults to all.

        Returns:
            Dictionary containing the requested markdown sections plus file
            bookkeeping (ignored_files, separate_extraction_files, main_output_files).
        """
        sections = list(sections) if sections else list(ALL_SECTIONS)

        all_files = data['files']

        ignored_files = [f['filename'] for f in all_files if self.should_ignore(f['filename'])]
        separate_extraction_files = [
            f for f in all_files if self.should_extract_separately(f['filename'])
        ]
        separate_output_names = self._separate_output_names(
            [f['filename'] for f in separate_extraction_files]
        )

        # Files matched for separate extraction are excluded from the main
        # output (Code.md) and are represented via standalone files.
        files = [
            f for f in all_files
            if not self.should_ignore(f['filename']) and not self.should_extract_separately(f['filename'])
        ]

        # Group files by category (used by code).
        files_by_category = {}
        for file_data in files:
            category = self.categorize_file(file_data['filename'])
            files_by_category.setdefault(category, []).append(file_data)

        # Map every changed file by path (used by feedback for code context).
        files_by_path = {f['filename']: f for f in all_files}

        result: Dict[str, Any] = {
            'sections': sections,
            'ignored_files': ignored_files,
            'separate_extraction_files': separate_extraction_files,
            'separate_output_names': separate_output_names,
            'main_output_files': [f['filename'] for f in files],
        }

        if 'code' in sections:
            result['code'] = self._build_code_md(files_by_category)
        if 'feedback' in sections:
            result['feedback'] = self._build_feedback_md(
                data, files_by_path, separate_output_names, with_code='code' in sections
            )

        return result

    def _separate_output_names(self, paths: List[str]) -> Dict[str, str]:
        """
        Relative output path of each separately extracted file: its group
        folder, then the file's own repository path plus '.md', e.g.
        ``MD/docs/setup.md.md`` or ``Config/src/Api/appsettings.json.md``.
        A leading dot is dropped from folder names (``.github`` -> ``github``)
        so tools that hide dot-folders, such as Obsidian, still show them.

        Args:
            paths: Paths of the separately extracted files

        Returns:
            Output path (forward slashes) for each path
        """
        names: Dict[str, str] = {}
        used = set()
        for path in paths:
            parts = list(PurePosixPath(self._normalize_path(path)).parts)
            folders = [part.lstrip('.') or part for part in parts[:-1]]
            base = '/'.join([self.extraction_group(path) or 'Other'] + folders + [parts[-1]])
            candidate, counter = f"{base}.md", 2
            while candidate in used:
                candidate = f"{base}__{counter}.md"
                counter += 1
            used.add(candidate)
            names[path] = candidate
        return names

    def _output_folder_name(self, kind: str, identifier: str, repo_name: str) -> str:
        """Build the output folder name for a PR or commit."""
        safe_repo = repo_name.replace('/', '_')
        if kind == 'commit':
            short_sha = identifier[:7]
            return f"Commit_{short_sha}_{safe_repo}"
        return f"PR_{identifier}_{safe_repo}"

    def save_sections(self, sections: Dict[str, Any], kind: str,
                      identifier: str, repo_name: str):
        """
        Save the generated sections to separate files in a folder on the desktop.

        Only the sections that were requested are written. The ignore/separate
        extraction reports and standalone extraction files are written only when
        the file-based code section was requested.

        Args:
            sections: Dictionary from :meth:`generate_markdown_sections`
            kind: 'pull' or 'commit'
            identifier: PR number or commit SHA
            repo_name: Repository name (owner_repo)
        """
        requested = sections.get('sections', list(ALL_SECTIONS))
        file_sections_requested = 'code' in requested

        desktop = Path.home() / 'Desktop'
        folder_name = self._output_folder_name(kind, identifier, repo_name)
        output_folder = desktop / folder_name

        # Create folder
        output_folder.mkdir(exist_ok=True)
        print(f"\nCreating output folder: {output_folder}")

        # Save Code.md
        if 'code' in sections:
            code_file = output_folder / 'Code.md'
            with open(code_file, 'w', encoding='utf-8') as f:
                f.write(sections['code'])
            print("  ✓ Saved: Code.md")

        # Save Feedback.md
        if 'feedback' in sections:
            feedback_file = output_folder / 'Feedback.md'
            with open(feedback_file, 'w', encoding='utf-8') as f:
                f.write(sections['feedback'])
            print("  ✓ Saved: Feedback.md")

        # The reports and standalone extraction files describe file-level
        # handling, so only emit them when a file-based section was requested.
        if not file_sections_requested:
            print(f"\n✓ All files saved to: {output_folder}")
            return

        separate_files = sections.get('separate_extraction_files', [])
        separate_names = sections.get('separate_output_names') or self._separate_output_names(
            [f['filename'] for f in separate_files]
        )

        reports_folder = output_folder / 'Reports'
        reports_folder.mkdir(exist_ok=True)

        # Save Reports/Ignore_Report.txt
        ignore_report_file = reports_folder / 'Ignore_Report.txt'
        with open(ignore_report_file, 'w', encoding='utf-8') as f:
            f.write("# Ignore Report\n")
            f.write("# Files matching Ignore.txt are left out of Code.md and are not extracted\n")
            f.write("# separately. Review comments on them still appear in Feedback.md.\n\n")

            f.write("## Ignore Patterns Used\n")
            f.write("# Loaded from: Ignore.txt in repository\n")
            f.write(f"# Total patterns: {len(self.ignore_patterns)}\n\n")
            for pattern in self.ignore_patterns:
                f.write(f"{pattern}\n")

            f.write("\n## Ignored Files\n")
            f.write(f"# Total files ignored: {len(sections['ignored_files'])}\n\n")
            if sections['ignored_files']:
                for ignored_file in sorted(sections['ignored_files']):
                    f.write(f"{ignored_file}\n")
            else:
                f.write("(No files were ignored)\n")
        print(f"  ✓ Saved: Reports/Ignore_Report.txt ({len(sections['ignored_files'])} files ignored)")

        # Save separately extracted file diffs under their group folder,
        # mirroring the repository path.
        generated_extraction_files = []
        for file_data in separate_files:
            filepath = file_data['filename']
            output_name = separate_names[filepath]
            generated_extraction_files.append((filepath, output_name))
            output_file = output_folder / output_name
            output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(self.format_code_changes(file_data))

        separate_report_file = reports_folder / 'SeparateExtraction_Report.txt'
        with open(separate_report_file, 'w', encoding='utf-8') as f:
            f.write("# Separate Extraction Report\n")
            f.write(
                "# This report shows which files matched SeparateExtractionList.txt "
                "and where they were written\n\n"
            )

            f.write("## Extraction Patterns Used\n")
            f.write("# Loaded from: SeparateExtractionList.txt in repository\n")
            f.write(f"# Total patterns: {len(self.separate_extraction_rules)}\n\n")
            if self.separate_extraction_rules:
                for group, pattern in self.separate_extraction_rules:
                    f.write(f"[{group}] {pattern}\n")
            else:
                f.write("(No patterns configured)\n")

            f.write("\n## Matched Files\n")
            f.write(f"# Total files matched: {len(generated_extraction_files)}\n\n")
            if generated_extraction_files:
                for source_file, output_name in sorted(generated_extraction_files):
                    f.write(f"{source_file} -> {output_name}\n")
            else:
                f.write("(No files matched)\n")

        print(
            f"  ✓ Saved: {len(separate_files)} separately extracted markdown diff file(s)"
        )
        print("  ✓ Saved: Reports/SeparateExtraction_Report.txt")

        print(f"\n✓ All files saved to: {output_folder}")

    def parse(self, url: str, sections: Optional[Sequence[str]] = None):
        """
        Main method to parse a PR or commit and generate markdown sections.

        Args:
            url: GitHub PR or commit URL
            sections: Which sections to extract (defaults to all)
        """
        try:
            sections = list(sections) if sections else list(ALL_SECTIONS)

            # Parse URL
            parsed = self.parse_url(url)
            kind = parsed['kind']
            subject = 'PR' if kind == 'pull' else 'commit'
            id_display = parsed['identifier'] if kind == 'pull' else parsed['identifier'][:7]
            print(f"Parsing {subject} {id_display} from {parsed['owner']}/{parsed['repo']}")
            print(f"Sections: {', '.join(sections)}")

            # Fetch data
            data = self.fetch_data(parsed)
            print(
                f"Found {len(data['files'])} files, {len(data['comments'])} inline comments, "
                f"{len(data['conversation'])} conversation comments and {len(data['reviews'])} reviews"
            )

            # Generate markdown sections
            print("Generating markdown sections...")
            generated = self.generate_markdown_sections(data, sections)

            # Count files included in the main Code output.
            processed_files = len(generated.get('main_output_files', []))
            print(
                f"Processing {processed_files} files "
                f"({len(generated['ignored_files'])} ignored, "
                f"{len(generated.get('separate_extraction_files', []))} separately extracted)"
            )

            # Save to desktop in separate files
            repo_name = f"{parsed['owner']}_{parsed['repo']}"
            self.save_sections(generated, kind, parsed['identifier'], repo_name)

            print("\n✓ Done!")

        except Exception as e:
            print(f"Error: {e}")
            raise


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog='GitHubParser',
        description='Extract code and/or feedback from a GitHub '
                    'pull request or commit into markdown files.',
        epilog='Authentication: set the GITHUB_TOKEN environment variable, or enter '
               'the token at the secure (no-echo) prompt. For security, the token is '
               'never accepted as a command-line argument.',
    )
    parser.add_argument(
        'url', nargs='?',
        help='GitHub PR (.../pull/123) or commit (.../commit/<sha>) URL. '
             'If omitted, you will be prompted.',
    )
    parser.add_argument(
        '-s', '--sections', '--only', dest='sections', metavar='LIST',
        help="Comma-separated sections to extract: code, feedback "
             "(alias: comments=feedback), or 'all'. Example: --only feedback. "
             "If omitted, you will be prompted (default: all).",
    )
    private_group = parser.add_mutually_exclusive_group()
    private_group.add_argument(
        '--private', dest='private', action='store_true', default=None,
        help='Treat the repository as private (requires a token). '
             'Skips the interactive private/public prompt.',
    )
    private_group.add_argument(
        '--public', dest='private', action='store_false',
        help='Treat the repository as public. Skips the interactive prompt.',
    )
    return parser


def main():
    """Main entry point for the script."""
    args = build_arg_parser().parse_args()

    print("=" * 60)
    print("GitHub Parser")
    print("=" * 60)
    print()

    # The token is only ever read from the environment or the secure prompt below,
    # never from a command-line argument (which would leak into shell history and
    # process listings).
    token = os.getenv('GITHUB_TOKEN')

    # Determine whether the repository is private.
    # --private/--public skip the prompt; otherwise ask interactively.
    if args.private is None:
        is_private_answer = input("Is this a private repository? (y/n): ").strip().lower()
        is_private = is_private_answer in ['y', 'yes']
    else:
        is_private = args.private

    if is_private:
        if token:
            print("\n✓ Using GitHub token from GITHUB_TOKEN environment variable")
        else:
            print("\nA GitHub personal access token is required for private repositories.")
            print("Create one at: https://github.com/settings/tokens")
            print("Required scope: 'repo' (Full control of private repositories)")
            token = getpass.getpass("\nEnter your GitHub token: ").strip()
            if not token:
                print("Error: No token provided. Cannot access private repository.")
                return
            print("✓ Token provided")

    # Initialize parser with token (loads Ignore.txt)
    parser = GitHubParser(token=token)

    # Show authentication status
    print()
    if parser.token:
        print("✓ Authenticated with GitHub token")
    else:
        print("ℹ Not authenticated - accessing public repository")

    # Show loaded ignore patterns
    if parser.ignore_patterns:
        print(f"\nIgnore patterns loaded from Ignore.txt ({len(parser.ignore_patterns)} patterns):")
        for pattern in parser.ignore_patterns:
            print(f"  - {pattern}")
    else:
        print("\n⚠ No ignore patterns loaded (Ignore.txt is empty or not found)")
        print("  Edit Ignore.txt in the repository to configure ignore patterns")

    # Show loaded separate extraction patterns
    if parser.separate_extraction_rules:
        print(
            f"\nSeparate extraction patterns loaded from SeparateExtractionList.txt "
            f"({len(parser.separate_extraction_rules)} patterns):"
        )
        for group, pattern in parser.separate_extraction_rules:
            print(f"  - [{group}] {pattern}")
    else:
        print("\n⚠ No separate extraction patterns loaded")
        print("  Edit SeparateExtractionList.txt in the repository to configure patterns")
    print()

    # Resolve which sections to extract.
    if args.sections is None:
        raw_sections = input(
            "Which sections to extract? "
            "[all / code / feedback] (comma-separated, default all): "
        ).strip()
    else:
        raw_sections = args.sections

    try:
        sections = resolve_sections(raw_sections)
    except ValueError as e:
        print(f"Error: {e}")
        return

    # Get URL from user (PR or commit).
    if args.url:
        url = args.url.strip()
    else:
        url = input("\nEnter GitHub PR or commit URL: ").strip()

    if not url:
        print("Error: No URL provided")
        return

    # Parse the PR or commit.
    parser.parse(url, sections=sections)


if __name__ == '__main__':
    main()
