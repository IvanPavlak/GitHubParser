#!/usr/bin/env python3
"""
GitHub Pull Request Parser
Extracts PR information and formats it into a structured markdown file.
"""

import os
import re
import getpass
import requests
from pathlib import Path
from typing import List, Dict, Any, Optional
from fnmatch import fnmatch


class GitHubPRParser:
    def __init__(self, token: Optional[str] = None, prignore_path: Optional[str] = None):
        """
        Initialize the parser with optional GitHub token.

        Args:
            token: GitHub personal access token. If None, will try to read from GITHUB_TOKEN env var.
            prignore_path: Path to PRIgnore.txt file. If None, looks in script directory.
        """
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
        }
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'

        # Load ignore patterns from PRIgnore.txt
        if prignore_path is None:
            script_dir = Path(__file__).parent
            prignore_path = script_dir / 'PRIgnore.txt'

        self.ignore_patterns = self.load_ignore_patterns(prignore_path)

    def load_ignore_patterns(self, prignore_path: Path) -> List[str]:
        """
        Load ignore patterns from PRIgnore.txt file.

        Args:
            prignore_path: Path to PRIgnore.txt file

        Returns:
            List of ignore patterns
        """
        patterns = []

        if not prignore_path.exists():
            print(f"Warning: PRIgnore.txt not found at {prignore_path}")
            print("Using empty ignore list. Create PRIgnore.txt to configure ignore patterns.")
            return patterns

        try:
            with open(prignore_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if line and not line.startswith('#'):
                        patterns.append(line)

            print(f"Loaded {len(patterns)} ignore pattern(s) from PRIgnore.txt")
        except Exception as e:
            print(f"Error reading PRIgnore.txt: {e}")
            print("Continuing with empty ignore list.")

        return patterns

    def parse_pr_url(self, url: str) -> tuple:
        """
        Parse GitHub PR URL to extract owner, repo, and PR number.

        Args:
            url: GitHub PR URL (e.g., https://github.com/owner/repo/pull/123)

        Returns:
            Tuple of (owner, repo, pr_number)
        """
        pattern = r'github\.com/([^/]+)/([^/]+)/pull/(\d+)'
        match = re.search(pattern, url)
        if not match:
            raise ValueError(f"Invalid GitHub PR URL: {url}")

        owner, repo, pr_number = match.groups()
        return owner, repo, pr_number

    def should_ignore(self, filepath: str) -> bool:
        """
        Check if a file should be ignored based on ignore patterns.

        Args:
            filepath: Path to the file

        Returns:
            True if file should be ignored, False otherwise
        """
        for pattern in self.ignore_patterns:
            if fnmatch(filepath, pattern):
                return True
        return False

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
        Fetch all pages of a paginated GitHub API endpoint.

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

    def fetch_pr_data(self, owner: str, repo: str, pr_number: str) -> Dict[str, Any]:
        """
        Fetch PR data from GitHub API with pagination support.

        Args:
            owner: Repository owner
            repo: Repository name
            pr_number: Pull request number

        Returns:
            Dictionary containing PR data
        """
        base_url = f'https://api.github.com/repos/{owner}/{repo}/pulls/{pr_number}'

        print(f"Fetching PR data from {base_url}...")

        # Fetch PR details
        pr_response = requests.get(base_url, headers=self.headers)

        if pr_response.status_code == 404:
            if self.token:
                raise ValueError(
                    f"PR not found or you don't have access to it.\n"
                    f"Please verify:\n"
                    f"  1. The PR URL is correct\n"
                    f"  2. Your GitHub token has the correct permissions (repo scope for private repos)\n"
                    f"  3. The repository and PR exist"
                )
            else:
                raise ValueError(
                    f"PR not found. This could mean:\n"
                    f"  1. The repository is private and requires authentication\n"
                    f"  2. The PR URL is incorrect\n"
                    f"  3. The repository or PR doesn't exist\n\n"
                    f"To access private repositories, set the GITHUB_TOKEN environment variable:\n"
                    f"  Windows (PowerShell): $env:GITHUB_TOKEN = 'your_token_here'\n"
                    f"  Windows (CMD): set GITHUB_TOKEN=your_token_here\n\n"
                    f"Create a token at: https://github.com/settings/tokens"
                )

        pr_response.raise_for_status()
        pr_data = pr_response.json()

        # Fetch files changed (with pagination)
        print("\nFetching changed files...")
        files_url = f'{base_url}/files'
        files_data = self.fetch_paginated(files_url, 'files')

        # Fetch review comments (with pagination)
        print("\nFetching review comments...")
        comments_url = f'{base_url}/comments'
        comments_data = self.fetch_paginated(comments_url, 'comments')

        return {
            'pr': pr_data,
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

    def format_comments(self, comments: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, str]]]:
        """
        Group and format comments by file.

        Args:
            comments: List of comment data from GitHub API

        Returns:
            Dictionary mapping filepath to list of comment data
        """
        comments_by_file = {}

        for comment in comments:
            filepath = comment.get('path', 'General')

            if filepath not in comments_by_file:
                comments_by_file[filepath] = []

            comments_by_file[filepath].append({
                'author': comment['user']['login'],
                'body': comment['body'],
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

    def generate_markdown_sections(self, pr_data: Dict[str, Any]) -> Dict[str, str]:
        """
        Generate separate markdown sections.

        Args:
            pr_data: Complete PR data including files and comments

        Returns:
            Dictionary with 'description', 'code', and 'feedback' markdown sections
        """
        all_files = pr_data['files']
        files = [f for f in all_files if not self.should_ignore(f['filename'])]
        ignored_files = [f['filename'] for f in all_files if self.should_ignore(f['filename'])]
        file_patches = {f['filename']: f.get('patch', '') for f in all_files}
        comments = pr_data['comments']

        # Group files by category
        files_by_category = {}
        for file_data in files:
            category = self.categorize_file(file_data['filename'])
            if category not in files_by_category:
                files_by_category[category] = []
            files_by_category[category].append(file_data)

        # === Description Section ===
        description_md = "# Description\n\n"

        for category in sorted(files_by_category.keys()):
            description_md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                filepath = file_data['filename']
                description_md += f"### `{filepath}`\n\n"
                description_md += "- Description\n\n"

        # === Code Section ===
        code_md = "# Code\n\n"

        for category in sorted(files_by_category.keys()):
            code_md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                code_md += self.format_code_changes(file_data)

        # === Feedback Section ===
        feedback_md = "# Feedback\n\n"
        comments_by_file = self.format_comments(comments)

        if comments_by_file:
            # First, build conversation threads based on reply chains
            all_threads = []
            for filepath, file_comments in comments_by_file.items():
                if self.should_ignore(filepath):
                    continue

                # Create a map of comment ID to comment
                comment_map = {c['id']: c for c in file_comments}

                # Find root comments (not replies to other comments)
                root_comments = [c for c in file_comments if not c['in_reply_to_id']]

                # Build threads: each root comment + all its replies
                for root_comment in root_comments:
                    thread = [root_comment]

                    # Find all replies to this root comment
                    replies = [c for c in file_comments if c['in_reply_to_id'] == root_comment['id']]
                    thread.extend(replies)

                    # Also check for nested replies (replies to replies)
                    for reply in replies:
                        nested_replies = [c for c in file_comments if c['in_reply_to_id'] == reply['id']]
                        thread.extend(nested_replies)

                    all_threads.append({
                        'filepath': filepath,
                        'comments': thread
                    })

            # Now process each thread with its own file header and code context
            for thread in all_threads:
                filepath = thread['filepath']
                thread_comments = thread['comments']

                # File header for each comment/conversation
                feedback_md += f"### `{filepath}`\n\n"

                # Show code context for this thread
                first_comment = thread_comments[0]
                if first_comment['code']:
                    extension = self.get_file_extension(filepath)
                    comment_line = first_comment.get('line', 0) or 0
                    start_line = first_comment.get('start_line') or None
                    context_lines = self.extract_comment_context(
                        first_comment['code'],
                        comment_line=comment_line,
                        start_line=start_line,
                    )

                    if context_lines:
                        feedback_md += f"```{extension}\n"
                        feedback_md += '\n'.join(context_lines)
                        feedback_md += "\n```\n\n"

                # Format comments based on thread size
                if len(thread_comments) == 1:
                    # Single comment - use bullet format with cleaned body
                    comment = thread_comments[0]
                    # Clean up extra newlines in comment body
                    clean_body = re.sub(r'\n\n+', '\n', comment['body']).strip()
                    feedback_md += f"- `{comment['author']}` → {clean_body}\n\n"
                else:
                    # Multiple comments - format as conversation in code block
                    feedback_md += "```\n"
                    for i, comment in enumerate(thread_comments):
                        author = comment['author']
                        body = comment['body']

                        # Clean up extra newlines - collapse multiple blank lines to single blank line
                        clean_body = re.sub(r'\n\n+', '\n\n', body).strip()

                        # Format with author and arrow
                        feedback_md += f"- {author} → "

                        # Check if body is multi-line
                        if '\n' in clean_body:
                            # Multi-line: put content on next line with indentation
                            feedback_md += "\n\n"
                            # Indent all lines, but don't add spaces to blank lines
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
                            # Single line: keep on same line
                            feedback_md += clean_body

                        # Add spacing between comments
                        if i < len(thread_comments) - 1:
                            feedback_md += "\n\n"

                    feedback_md += "\n```\n\n"

        else:
            feedback_md += "No comments found.\n"

        return {
            'description': description_md,
            'code': code_md,
            'feedback': feedback_md,
            'ignored_files': ignored_files
        }

    def save_pr_sections(self, sections: Dict[str, str], pr_number: str, repo_name: str):
        """
        Save PR sections to separate files in a folder on the desktop.

        Args:
            sections: Dictionary containing markdown sections and ignored files
            pr_number: PR number
            repo_name: Repository name
        """
        desktop = Path.home() / 'Desktop'
        folder_name = f"PR_{pr_number}_{repo_name.replace('/', '_')}"
        pr_folder = desktop / folder_name

        # Create folder
        pr_folder.mkdir(exist_ok=True)
        print(f"\nCreating PR folder: {pr_folder}")

        # Save Description.md
        desc_file = pr_folder / 'Description.md'
        with open(desc_file, 'w', encoding='utf-8') as f:
            f.write(sections['description'])
        print(f"  ✓ Saved: Description.md")

        # Save Code.md
        code_file = pr_folder / 'Code.md'
        with open(code_file, 'w', encoding='utf-8') as f:
            f.write(sections['code'])
        print(f"  ✓ Saved: Code.md")

        # Save Feedback.md
        feedback_file = pr_folder / 'Feedback.md'
        with open(feedback_file, 'w', encoding='utf-8') as f:
            f.write(sections['feedback'])
        print(f"  ✓ Saved: Feedback.md")

        # Save PRIgnore_Report.txt
        prignore_report_file = pr_folder / 'PRIgnore_Report.txt'
        with open(prignore_report_file, 'w', encoding='utf-8') as f:
            f.write("# PRIgnore Report\n")
            f.write("# This report shows which files were ignored during PR parsing\n\n")

            f.write("## Ignore Patterns Used\n")
            f.write(f"# Loaded from: PRIgnore.txt in repository\n")
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
        print(f"  ✓ Saved: PRIgnore_Report.txt ({len(sections['ignored_files'])} files ignored)")

        print(f"\n✓ All files saved to: {pr_folder}")

    def parse(self, pr_url: str):
        """
        Main method to parse a PR and generate markdown sections.

        Args:
            pr_url: GitHub PR URL
        """
        try:
            # Parse URL
            owner, repo, pr_number = self.parse_pr_url(pr_url)
            print(f"Parsing PR #{pr_number} from {owner}/{repo}")

            # Fetch data
            pr_data = self.fetch_pr_data(owner, repo, pr_number)
            total_files = len(pr_data['files'])
            total_comments = len(pr_data['comments'])
            print(f"Found {total_files} files and {total_comments} comments")

            # Generate markdown sections
            print("Generating markdown sections...")
            sections = self.generate_markdown_sections(pr_data)

            # Count processed files
            processed_files = total_files - len(sections['ignored_files'])
            print(f"Processing {processed_files} files ({len(sections['ignored_files'])} ignored)")

            # Save to desktop in separate files
            repo_name = f"{owner}_{repo}"
            self.save_pr_sections(sections, pr_number, repo_name)

            print("\n✓ Done!")

        except Exception as e:
            print(f"Error: {e}")
            raise


def main():
    """Main entry point for the script."""
    print("=" * 60)
    print("GitHub Pull Request Parser")
    print("=" * 60)
    print()

    # Check if token exists in environment
    env_token = os.getenv('GITHUB_TOKEN')
    token = env_token

    # Ask if the repository is private
    is_private = input("Is this a private repository? (y/n): ").strip().lower()

    if is_private in ['y', 'yes']:
        if env_token:
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

    # Initialize parser with token (loads PRIgnore.txt)
    parser = GitHubPRParser(token=token)

    # Show authentication status
    print()
    if parser.token:
        print("✓ Authenticated with GitHub token")
    else:
        print("ℹ Not authenticated - accessing public repository")

    # Show loaded ignore patterns
    if parser.ignore_patterns:
        print(f"\nIgnore patterns loaded from PRIgnore.txt ({len(parser.ignore_patterns)} patterns):")
        for pattern in parser.ignore_patterns:
            print(f"  - {pattern}")
    else:
        print("\n⚠ No ignore patterns loaded (PRIgnore.txt is empty or not found)")
        print("  Edit PRIgnore.txt in the repository to configure ignore patterns")
    print()

    # Get PR URL from user
    pr_url = input("Enter GitHub PR URL: ").strip()

    if not pr_url:
        print("Error: No URL provided")
        return

    # Parse the PR
    parser.parse(pr_url)


if __name__ == '__main__':
    main()
