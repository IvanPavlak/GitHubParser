function GitHubPullRequestParser {
	$currentDirectory = Get-Location

	Set-Location -Path $MachineSpecificPaths.GitHubPullRequestParserDirectory

	try {
		$batFile = Join-Path (Get-Location) "GitHubPullRequestParser.bat"
		& cmd /c "`"$batFile`""
		Write-Host -ForegroundColor Green "`n=> GitHub Pull Request Parsing Completed!"
	}
	catch {
		Write-Host -ForegroundColor Red "`n=> Error during GitHub Pull Request Parsing!"
		Write-Host -ForegroundColor Red $_.Exception.Message
	}
	finally {
		Set-Location -Path $currentDirectory
	}
}
