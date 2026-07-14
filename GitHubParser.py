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
import sys
import getpass
import argparse
import requests
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
                 separate_extraction_list_path: Optional[str] = None):
        """
        Initialize the parser with an optional GitHub token.

        Args:
            token: GitHub personal access token. If None, will try to read from GITHUB_TOKEN env var.
            ignore_path: Path to Ignore.txt file. If None, looks in script directory.
            separate_extraction_list_path: Path to SeparateExtractionList.txt file.
                If None, looks in script directory.
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

        self.ignore_patterns = self.load_patterns_file(ignore_path, 'Ignore.txt')
        self.separate_extraction_patterns = self.load_patterns_file(
            separate_extraction_list_path,
            'SeparateExtractionList.txt'
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

    def load_ignore_patterns(self, ignore_path: Path) -> List[str]:
        """Backward-compatible wrapper for loading Ignore.txt."""
        return self.load_patterns_file(ignore_path, 'Ignore.txt')

    def matches_patterns(self, filepath: str, patterns: List[str]) -> bool:
        """
        Match a filepath against an ordered list of glob patterns.

        Supports optional negation via leading '!'.
        Last matching pattern wins.
        """
        normalized_filepath = filepath.replace('\\', '/').lstrip('./')
        matched = False

        for pattern in patterns:
            is_negation = pattern.startswith('!')
            actual_pattern = pattern[1:] if is_negation else pattern

            # Normalize slashes so patterns work regardless of separator style.
            normalized_pattern = actual_pattern.replace('\\', '/').lstrip('./')

            is_match = (
                fnmatch(filepath, actual_pattern) or
                fnmatch(normalized_filepath, normalized_pattern)
            )

            if is_match:
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

    def should_extract_separately(self, filepath: str) -> bool:
        """Check if a file should be separately extracted based on patterns."""
        return self.matches_patterns(filepath, self.separate_extraction_patterns)

    def add_ignore_patterns(self, patterns: List[str]):
        """Add custom ignore patterns."""
        self.ignore_patterns.extend(patterns)

    def categorize_file(self, filepath: str) -> str:
        """
        Categorize file as Backend, Frontend, or Other based on path.

        Args:
            filepath: Path to the file

        Returns:
            Category name
        """
        if filepath.startswith('api/') or filepath.endswith(('.cs', '.java', '.py', '.go')):
            return 'Backend'
        elif filepath.startswith('ui/') or filepath.startswith('frontend/') or \
             filepath.endswith(('.ts', '.tsx', '.jsx', '.vue')):
            return 'Frontend'
        else:
            return 'Other'

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
            response = requests.get(url, headers=self.headers, params=params)
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
            Unified dict: {kind, owner, repo, identifier, meta, files, comments}
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
          * review summary bodies   (/pulls/{n}/reviews)    – the message submitted with
                                                              an Approve/Comment/Request-changes review

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
        pr_response = requests.get(base_url, headers=self.headers)
        if pr_response.status_code == 404:
            self._handle_not_found('pull')
        pr_response.raise_for_status()
        pr_data = pr_response.json()

        # Fetch files changed (with pagination)
        print("\nFetching changed files...")
        files_data = self.fetch_paginated(f'{base_url}/files', 'files')

        # A PR carries three separate comment streams. Previously only the
        # inline one was fetched, so any feedback left in the Conversation tab
        # or as a review summary was silently dropped.
        print("\nFetching inline review comments...")
        review_comments = self.fetch_paginated(f'{base_url}/comments', 'comments')

        print("\nFetching conversation comments...")
        issue_comments = self.fetch_paginated(f'{issue_url}/comments', 'comments')

        print("\nFetching review summaries...")
        reviews = self.fetch_paginated(f'{base_url}/reviews', 'reviews')
        # Keep only reviews that carry an actual message; a bare approval or a
        # review that merely bundles inline notes has an empty body and would
        # otherwise render as a blank entry.
        review_summaries = [r for r in reviews if (r.get('body') or '').strip()]

        # Inline comments keep their file/diff anchoring; conversation comments
        # and review summaries have no `path`, so format_comments() files them
        # under the "General" section automatically.
        comments_data = review_comments + issue_comments + review_summaries

        return {
            'kind': 'pull',
            'owner': owner,
            'repo': repo,
            'identifier': pr_number,
            'meta': pr_data,
            'files': files_data,
            'comments': comments_data,
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
        commit_response = requests.get(
            base_url, headers=self.headers, params={'per_page': 100, 'page': 1}
        )
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
                response = requests.get(
                    base_url, headers=self.headers, params={'per_page': 100, 'page': page}
                )
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

        return {
            'kind': 'commit',
            'owner': owner,
            'repo': repo,
            'identifier': sha,
            'meta': commit_data,
            'files': files_data,
            'comments': comments_data,
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

        # Check if file was deleted
        if status == 'removed':
            output = f"### `{filepath}`\n\n"
            output += f"```{extension}\n"
            output += "// Old\n...\n"

            # Extract the old code from the patch
            if patch:
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

        if not patch:
            return ''

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

    def _extract_lines_by_range(self, full_patch: str, start_line: int, end_line: int) -> List[str]:
        """
        Extract exact lines from *start_line* to *end_line* (inclusive) using
        the new-file side of a patch.

        Args:
            full_patch: The complete file patch
            start_line: First line number to include
            end_line: Last line number to include

        Returns:
            List of code lines in the requested range
        """
        line_map = self._build_new_line_map(full_patch)
        return [code for num, code in line_map if start_line <= num <= end_line]

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
            comment_line: Line number in the new file (GitHub 'line' field)
            start_line: First line of a multi-line selection (GitHub 'start_line')

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

    def format_comments(self, comments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
        """
        Group and format comments by file.

        Handles both PR review comments (which carry diff_hunk / reply threading)
        and commit comments (which do not). Missing fields degrade gracefully via
        ``.get()`` defaults.

        Args:
            comments: List of comment data from GitHub API

        Returns:
            Dictionary mapping filepath to list of comment data
        """
        comments_by_file = {}

        for comment in comments:
            filepath = comment.get('path') or 'General'

            if filepath not in comments_by_file:
                comments_by_file[filepath] = []

            comments_by_file[filepath].append({
                'author': (comment.get('user') or {}).get('login', 'unknown'),
                'body': comment.get('body', ''),
                'code': comment.get('diff_hunk', ''),
                'position': comment.get('position', 0),
                'id': comment.get('id'),
                'in_reply_to_id': comment.get('in_reply_to_id'),
                'line': comment.get('line', 0),
                'original_line': comment.get('original_line', 0),
                'start_line': comment.get('start_line'),
                'original_start_line': comment.get('original_start_line'),
                'side': comment.get('side'),
                'start_side': comment.get('start_side'),
            })

        return comments_by_file

    def _build_code_md(self, files_by_category: Dict[str, List[Dict[str, Any]]]) -> str:
        """Build the Code.md content from categorized files."""
        code_md = "# Code\n\n"
        for category in sorted(files_by_category.keys()):
            code_md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                code_md += self.format_code_changes(file_data)
        return code_md

    def _build_feedback_md(self, comments: List[Dict[str, Any]],
                           files_by_path: Dict[str, Dict[str, Any]]) -> str:
        """
        Build the Feedback.md content from comments.

        Code context for a comment is sourced from the comment's diff_hunk
        (PR review comments). When no diff_hunk is present (commit comments),
        it falls back to the file's full patch using the comment's line number.
        """
        feedback_md = "# Feedback\n\n"
        comments_by_file = self.format_comments(comments)

        if not comments_by_file:
            feedback_md += "No comments found.\n"
            return feedback_md

        # First, build conversation threads based on reply chains.
        all_threads = []
        for filepath, file_comments in comments_by_file.items():
            if filepath != 'General' and self.should_ignore(filepath):
                continue

            # Find root comments (not replies to other comments).
            root_comments = [c for c in file_comments if not c['in_reply_to_id']]

            # Build threads: each root comment + all its replies.
            for root_comment in root_comments:
                thread = [root_comment]

                # Find all replies to this root comment. Guard against a
                # None == None match (commit comments / comments without ids)
                # which would otherwise make a comment a reply to itself.
                replies = [
                    c for c in file_comments
                    if c['in_reply_to_id'] is not None
                    and c['in_reply_to_id'] == root_comment['id']
                ]
                thread.extend(replies)

                # Also check for nested replies (replies to replies).
                for reply in replies:
                    nested_replies = [
                        c for c in file_comments
                        if c['in_reply_to_id'] is not None
                        and c['in_reply_to_id'] == reply['id']
                    ]
                    thread.extend(nested_replies)

                all_threads.append({
                    'filepath': filepath,
                    'comments': thread
                })

        if not all_threads:
            feedback_md += "No comments found.\n"
            return feedback_md

        # Now process each thread with its own file header and code context.
        for thread in all_threads:
            filepath = thread['filepath']
            thread_comments = thread['comments']

            # File header for each comment/conversation.
            feedback_md += f"### `{filepath}`\n\n"

            # Show code context for this thread.
            first_comment = thread_comments[0]
            extension = self.get_file_extension(filepath)
            context_lines = []

            if first_comment['code']:
                # PR review comment: the diff_hunk is the comment-time snapshot,
                # anchored by line / start_line.
                comment_line = first_comment.get('line', 0) or 0
                start_line = first_comment.get('start_line') or None
                context_lines = self.extract_comment_context(
                    first_comment['code'],
                    comment_line=comment_line,
                    start_line=start_line,
                )
            elif filepath != 'General':
                # Commit comment: no diff_hunk. GitHub anchors it by `position`
                # (an index into the file's diff); the `line` field is often
                # absent. Source the snippet from the file's full patch.
                file_data = files_by_path.get(filepath)
                full_patch = file_data.get('patch', '') if file_data else ''
                if full_patch:
                    position = first_comment.get('position') or 0
                    comment_line = first_comment.get('line', 0) or 0
                    if position:
                        context_lines = self._extract_context_by_position(full_patch, position)
                    elif comment_line:
                        context_lines = self._extract_lines_with_context(full_patch, comment_line)

            if context_lines:
                feedback_md += f"```{extension}\n"
                feedback_md += '\n'.join(context_lines)
                feedback_md += "\n```\n\n"

            # Format comments based on thread size.
            if len(thread_comments) == 1:
                # Single comment - use bullet format with cleaned body.
                comment = thread_comments[0]
                # Clean up extra newlines in comment body.
                clean_body = re.sub(r'\n\n+', '\n', comment['body']).strip()
                feedback_md += f"- `{comment['author']}` → {clean_body}\n\n"
            else:
                # Multiple comments - format as conversation in code block.
                feedback_md += "```\n"
                for i, comment in enumerate(thread_comments):
                    author = comment['author']
                    body = comment['body']

                    # Clean up extra newlines - collapse multiple blank lines to single blank line.
                    clean_body = re.sub(r'\n\n+', '\n\n', body).strip()

                    # Format with author and arrow.
                    feedback_md += f"- {author} → "

                    # Check if body is multi-line.
                    if '\n' in clean_body:
                        # Multi-line: put content on next line with indentation.
                        feedback_md += "\n\n"
                        # Indent all lines, but don't add spaces to blank lines.
                        lines = clean_body.split('\n')
                        indented_lines = []
                        for line in lines:
                            if line.strip():  # Non-blank line
                                indented_lines.append('    ' + line)
                            else:  # Blank line
                                indented_lines.append('')
                        indented_body = '\n'.join(indented_lines)
                        feedback_md += indented_body
                    else:
                        # Single line: keep on same line.
                        feedback_md += clean_body

                    # Add spacing between comments.
                    if i < len(thread_comments) - 1:
                        feedback_md += "\n\n"

                feedback_md += "\n```\n\n"

        return feedback_md

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
        comments = data['comments']

        ignored_files = [f['filename'] for f in all_files if self.should_ignore(f['filename'])]
        separate_extraction_files = [
            f for f in all_files if self.should_extract_separately(f['filename'])
        ]

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
            'main_output_files': [f['filename'] for f in files],
        }

        if 'code' in sections:
            result['code'] = self._build_code_md(files_by_category)
        if 'feedback' in sections:
            result['feedback'] = self._build_feedback_md(comments, files_by_path)

        return result

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

        # Save Ignore_Report.txt
        ignore_report_file = output_folder / 'Ignore_Report.txt'
        with open(ignore_report_file, 'w', encoding='utf-8') as f:
            f.write("# Ignore Report\n")
            f.write("# This report shows which files were ignored during parsing\n\n")

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
        print(f"  ✓ Saved: Ignore_Report.txt ({len(sections['ignored_files'])} files ignored)")

        # Save separately extracted file diffs as markdown files in the root folder.
        separate_files = sections.get('separate_extraction_files', [])
        used_output_names = set()
        generated_extraction_files = []
        for file_data in separate_files:
            filepath = file_data['filename']
            status = file_data.get('status', '')
            source_name = PurePosixPath(filepath).name
            output_name = f"{source_name}.md"

            # Avoid overwriting when two files share the same base filename.
            if output_name in used_output_names:
                source_stem = PurePosixPath(filepath).stem
                source_suffix = PurePosixPath(filepath).suffix
                counter = 2
                while True:
                    candidate = f"{source_stem}__{counter}{source_suffix}.md"
                    if candidate not in used_output_names:
                        output_name = candidate
                        break
                    counter += 1

            used_output_names.add(output_name)
            output_file = output_folder / output_name
            extracted_md = self.format_code_changes(file_data)
            generated_extraction_files.append((filepath, output_name))

            with open(output_file, 'w', encoding='utf-8') as f:
                if extracted_md:
                    f.write(extracted_md)
                else:
                    # Keep fallback output in markdown when GitHub provides no textual patch.
                    f.write(f"### `{filepath}`\n\n")
                    f.write("No textual patch available from GitHub for this file.\n\n")
                    f.write(f"- Status: `{status}`\n")

        separate_report_file = output_folder / 'SeparateExtraction_Report.txt'
        with open(separate_report_file, 'w', encoding='utf-8') as f:
            f.write("# Separate Extraction Report\n")
            f.write(
                "# This report shows which files matched SeparateExtractionList.txt "
                "and where they were written\n\n"
            )

            f.write("## Extraction Patterns Used\n")
            f.write("# Loaded from: SeparateExtractionList.txt in repository\n")
            f.write(f"# Total patterns: {len(self.separate_extraction_patterns)}\n\n")
            if self.separate_extraction_patterns:
                for pattern in self.separate_extraction_patterns:
                    f.write(f"{pattern}\n")
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
        print("  ✓ Saved: SeparateExtraction_Report.txt")

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
            total_files = len(data['files'])
            total_comments = len(data['comments'])
            print(f"Found {total_files} files and {total_comments} comments")

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
    if parser.separate_extraction_patterns:
        print(
            f"\nSeparate extraction patterns loaded from SeparateExtractionList.txt "
            f"({len(parser.separate_extraction_patterns)} patterns):"
        )
        for pattern in parser.separate_extraction_patterns:
            print(f"  - {pattern}")
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
