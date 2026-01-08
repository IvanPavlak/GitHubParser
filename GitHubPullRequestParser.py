#!/usr/bin/env python3
"""
GitHub Pull Request Parser
Extracts PR information and formats it into a structured markdown file.
"""

import os
import re
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

    def extract_comment_context(self, diff_hunk: str, context_before: int = 2, context_after: int = 2) -> List[str]:
        """
        Extract the commented line with context lines above and below it from a diff hunk.

        Args:
            diff_hunk: The diff hunk containing the commented code
            context_before: Number of lines to show before the commented line (default: 2)
            context_after: Number of lines to show after the commented line (default: 2)

        Returns:
            List of code lines with context (up to context_before + 1 + context_after lines)
        """
        if not diff_hunk:
            return []

        # Normalize line endings
        diff_hunk = diff_hunk.replace('\r\n', '\n').replace('\r', '\n')
        lines = diff_hunk.split('\n')

        # Extract actual code lines (skip @@ headers and file markers)
        code_lines = []
        for line in lines:
            if not line:
                continue
            # Skip diff headers
            if line.startswith('@@') or line.startswith('---') or line.startswith('+++'):
                continue
            # Extract the actual code (remove diff prefix: ' ', '+', '-')
            if line and line[0] in [' ', '+', '-']:
                code_lines.append(line[1:])
            else:
                code_lines.append(line)

        if not code_lines:
            return []

        # GitHub comments typically point to a specific line in the diff
        # We'll show context_before + commented line + context_after
        # For simplicity, we'll extract from the middle of the hunk
        total_lines = len(code_lines)
        target_lines = context_before + 1 + context_after

        # If we have fewer lines than needed, return all lines
        if total_lines <= target_lines:
            return code_lines

        # Extract a window from the middle-to-end of the diff
        # (comments are often near the end of what's shown)
        start_idx = max(0, total_lines - target_lines - 1)
        end_idx = min(total_lines, start_idx + target_lines)

        return code_lines[start_idx:end_idx]

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
            for filepath, file_comments in comments_by_file.items():
                if self.should_ignore(filepath):
                    continue

                feedback_md += f"### `{filepath}`\n\n"

                for comment in file_comments:
                    # Add code snippet if available
                    if comment['code']:
                        extension = self.get_file_extension(filepath)
                        # Extract the commented line with 2 lines above and 2 lines below
                        context_lines = self.extract_comment_context(comment['code'], context_before=2, context_after=2)

                        if context_lines:
                            feedback_md += f"```{extension}\n"
                            feedback_md += '\n'.join(context_lines)
                            feedback_md += "\n```\n\n"

                    # Add comment
                    feedback_md += f"- `{comment['author']}` → {comment['body']}\n"

                feedback_md += "\n"
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

    # Initialize parser (loads PRIgnore.txt)
    parser = GitHubPRParser()

    # Show authentication status
    print()
    if parser.token:
        print("✓ Authenticated with GitHub token")
    else:
        print("⚠ Not authenticated - only public repositories accessible")
        print("  Set GITHUB_TOKEN environment variable for private repos")

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
