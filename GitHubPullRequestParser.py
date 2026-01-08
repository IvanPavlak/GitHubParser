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
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the parser with optional GitHub token.

        Args:
            token: GitHub personal access token. If None, will try to read from GITHUB_TOKEN env var.
        """
        self.token = token or os.getenv('GITHUB_TOKEN')
        self.headers = {
            'Accept': 'application/vnd.github.v3+json',
        }
        if self.token:
            self.headers['Authorization'] = f'token {self.token}'

        # Default ignore patterns (similar to gitignore)
        self.ignore_patterns = [
            '**/Migrations/*',
            '**/migrations/*',
            '**/*.min.js',
            '**/*.min.css',
            '**/node_modules/*',
            '**/package-lock.json',
            '**/yarn.lock',
        ]

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

    def fetch_pr_data(self, owner: str, repo: str, pr_number: str) -> Dict[str, Any]:
        """
        Fetch PR data from GitHub API.

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

        # Fetch files changed
        files_url = f'{base_url}/files'
        files_response = requests.get(files_url, headers=self.headers)
        files_response.raise_for_status()
        files_data = files_response.json()

        # Fetch review comments
        comments_url = f'{base_url}/comments'
        comments_response = requests.get(comments_url, headers=self.headers)
        comments_response.raise_for_status()
        comments_data = comments_response.json()

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
        patch = file_data.get('patch', '')

        if not patch:
            return ''

        # Parse the patch to extract old and new code sections
        lines = patch.split('\n')
        old_sections = []
        new_sections = []
        current_old = []
        current_new = []

        for line in lines:
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
                # Removed line
                current_old.append(line[1:])
            elif line.startswith('+') and not line.startswith('+++'):
                # Added line
                current_new.append(line[1:])
            elif line.startswith(' '):
                # Context line
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
            output += '\n...\n'.join(new_sections)
        else:
            # Show old and new sections
            output += "// Old\n"
            output += '...\n' + '\n...\n'.join(old_sections) + '\n...\n'
            output += "\n// New\n"
            output += '...\n' + '\n...\n'.join(new_sections) + '\n...\n'

        output += "```\n\n"

        return output

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

    def generate_markdown(self, pr_data: Dict[str, Any]) -> str:
        """
        Generate the final markdown output.

        Args:
            pr_data: Complete PR data including files and comments

        Returns:
            Formatted markdown string
        """
        files = [f for f in pr_data['files'] if not self.should_ignore(f['filename'])]
        comments = pr_data['comments']

        # Group files by category
        files_by_category = {}
        for file_data in files:
            category = self.categorize_file(file_data['filename'])
            if category not in files_by_category:
                files_by_category[category] = []
            files_by_category[category].append(file_data)

        # Start building markdown
        md = "# Description\n\n"

        # Description section with file headers
        for category in sorted(files_by_category.keys()):
            md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                filepath = file_data['filename']
                md += f"### `{filepath}`\n\n"
                md += "- Description\n"
            md += "\n"

        md += "___\n# Code\n\n"

        # Code section with changes
        for category in sorted(files_by_category.keys()):
            md += f"## {category}\n\n"
            for file_data in files_by_category[category]:
                md += self.format_code_changes(file_data)

        # Feedback section with comments
        comments_by_file = self.format_comments(comments)

        if comments_by_file:
            md += "___\n# Feedback\n\n"

            for filepath, file_comments in comments_by_file.items():
                if self.should_ignore(filepath):
                    continue

                md += f"### `{filepath}`\n\n"

                for comment in file_comments:
                    # Add code snippet if available
                    if comment['code']:
                        extension = self.get_file_extension(filepath)
                        # Extract just the relevant code from diff hunk
                        code_lines = comment['code'].split('\n')
                        clean_code = []
                        for line in code_lines:
                            if not line.startswith('@@'):
                                clean_line = line[1:] if line and line[0] in [' ', '+', '-'] else line
                                clean_code.append(clean_line)

                        md += f"```{extension}\n"
                        md += '\n'.join(clean_code)
                        md += "\n```\n\n"

                    # Add comment
                    md += f"- `{comment['author']}` → {comment['body']}\n"

                md += "\n"

        md += "___\n"

        return md

    def save_to_desktop(self, content: str, filename: str = 'pr_review.md'):
        """
        Save content to a file on the desktop.

        Args:
            content: Content to save
            filename: Name of the file
        """
        desktop = Path.home() / 'Desktop'
        filepath = desktop / filename

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

        print(f"\nMarkdown file saved to: {filepath}")

    def parse(self, pr_url: str, output_filename: Optional[str] = None):
        """
        Main method to parse a PR and generate markdown.

        Args:
            pr_url: GitHub PR URL
            output_filename: Optional output filename (default: pr_review.md)
        """
        try:
            # Parse URL
            owner, repo, pr_number = self.parse_pr_url(pr_url)
            print(f"Parsing PR #{pr_number} from {owner}/{repo}")

            # Fetch data
            pr_data = self.fetch_pr_data(owner, repo, pr_number)
            print(f"Found {len(pr_data['files'])} files and {len(pr_data['comments'])} comments")

            # Generate markdown
            markdown = self.generate_markdown(pr_data)

            # Save to desktop
            if output_filename is None:
                output_filename = f"pr_{pr_number}_review.md"

            self.save_to_desktop(markdown, output_filename)

            print("✓ Done!")

        except Exception as e:
            print(f"Error: {e}")
            raise


def main():
    """Main entry point for the script."""
    print("=" * 60)
    print("GitHub Pull Request Parser")
    print("=" * 60)
    print()

    # Get PR URL from user
    pr_url = input("Enter GitHub PR URL: ").strip()

    if not pr_url:
        print("Error: No URL provided")
        return

    # Ask about custom ignore patterns
    custom_ignores = input("\nEnter custom ignore patterns (comma-separated, or press Enter to skip): ").strip()

    # Initialize parser
    parser = GitHubPRParser()

    # Show authentication status
    if parser.token:
        print("✓ Authenticated with GitHub token")
    else:
        print("⚠ Not authenticated - only public repositories accessible")
        print("  Set GITHUB_TOKEN environment variable for private repos")

    # Add custom ignore patterns if provided
    if custom_ignores:
        patterns = [p.strip() for p in custom_ignores.split(',')]
        parser.add_ignore_patterns(patterns)
        print(f"Added {len(patterns)} custom ignore pattern(s)")

    print(f"\nUsing ignore patterns:")
    for pattern in parser.ignore_patterns:
        print(f"  - {pattern}")
    print()

    # Parse the PR
    parser.parse(pr_url)


if __name__ == '__main__':
    main()
