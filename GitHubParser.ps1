function GitHubParser {
	<#
	.SYNOPSIS
		Runs the GitHub Parser (pull request / commit -> markdown) in its configured directory.

	.DESCRIPTION
		Navigates to `$MachineSpecificPaths.GitHubParserDirectory`, runs `GitHubParser.bat`
		(which activates the conda environment and invokes `GitHubParser.py`), and restores the
		original working directory on exit.

		The -Url, -Sections, -Private and -Public parameters mirror flags of the underlying
		Python CLI and are forwarded straight through, so the tool can be driven entirely from
		PowerShell in the same manner as `python GitHubParser.py`. With no parameters the Python
		script runs interactively (prompting for private/public, sections, and the URL); supplying
		a parameter skips its matching prompt.

		The token is handled securely: it is NEVER passed as a command-line argument (which would
		leak into shell history and process listings). Provide it as a SecureString via -Token, or
		set the GITHUB_TOKEN environment variable yourself. When -Token is given, its value is
		placed in GITHUB_TOKEN only for the child process and removed again when the function
		returns. If neither is supplied for a private repo, the Python script prompts for it with
		no echo.

	.PARAMETER Url
		GitHub pull request (`.../pull/<number>`) or commit (`.../commit/<sha>`) URL. A trailing
		`#diff-...` fragment is ignored. Prompted if omitted.

	.PARAMETER Sections
		Comma-separated sections to extract: `code`, `feedback` (alias:
		`comments` = `feedback`), or `all`. Also accepts `-Only`. Prompted if omitted (default: all).

	.PARAMETER Token
		GitHub personal access token as a SecureString (e.g. `-Token (Read-Host -AsSecureString)`).
		Passed to the parser only through the GITHUB_TOKEN environment variable, never on the
		command line. If omitted, the existing GITHUB_TOKEN environment variable is used, or the
		Python script prompts securely.

	.PARAMETER Private
		Treat the repository as private (requires a token). Skips the private/public prompt.

	.PARAMETER Public
		Treat the repository as public. Skips the private/public prompt.

	.EXAMPLE
		GitHubParser
		Runs interactively (prompts for private/public, sections, and the URL).

	.EXAMPLE
		GitHubParser -Only feedback https://github.com/owner/repo/commit/<sha>
		Extracts only the feedback (comments) from a commit.

	.EXAMPLE
		GitHubParser -Sections code,feedback -Public https://github.com/owner/repo/pull/123
		Extracts code + feedback from a public pull request with no prompts.

	.EXAMPLE
		GitHubParser -Private -Token (Read-Host -AsSecureString) -Only feedback <url>
		Prompts (no echo) for a token, then extracts feedback from a private repository. The token
		never appears on the command line, in history, or in any process argument list.
	#>
	[CmdletBinding(DefaultParameterSetName = 'Default')]
	param(
		[Parameter(Position = 0)]
		[string]$Url,

		[Alias('Only')]
		[string[]]$Sections,

		[securestring]$Token,

		[Parameter(ParameterSetName = 'Private')]
		[switch]$Private,

		[Parameter(ParameterSetName = 'Public')]
		[switch]$Public
	)

	# Forward only the parameters the caller actually supplied; anything omitted
	# falls through to the Python script's interactive prompt. The token is
	# deliberately NOT forwarded here - it travels via the environment only.
	$parserArgs = @()
	if ($Sections) { $parserArgs += @('--sections', ($Sections -join ',')) }
	if ($Private) { $parserArgs += '--private' }
	if ($Public) { $parserArgs += '--public' }
	if ($Url) { $parserArgs += $Url }

	# Capture the current GITHUB_TOKEN so we can restore it afterward; only touch it
	# when a token was supplied to this call. GetEnvironmentVariable returns $null
	# when unset, and SetEnvironmentVariable($null) removes it - so a single restore
	# call cleanly resets to either the prior value or "unset".
	$previousToken = [System.Environment]::GetEnvironmentVariable('GITHUB_TOKEN')

	$currentDirectory = Get-Location

	Set-Location -Path $MachineSpecificPaths.GitHubParserDirectory

	try {
		if ($Token) {
			# Decrypt in-memory only long enough to hand it to the child process
			# through the environment (never through an argument).
			[System.Environment]::SetEnvironmentVariable('GITHUB_TOKEN', [System.Net.NetworkCredential]::new('', $Token).Password)
		}

		& ".\GitHubParser.bat" @parserArgs
		Write-Host -ForegroundColor Green "`n=> GitHub Parsing Completed!"
	}
	catch {
		Write-Host -ForegroundColor Red "`n=> Error during GitHub Parsing!"
		Write-Host -ForegroundColor Red $_.Exception.Message
	}
	finally {
		if ($Token) {
			[System.Environment]::SetEnvironmentVariable('GITHUB_TOKEN', $previousToken)
		}
		Set-Location -Path $currentDirectory
	}
}
