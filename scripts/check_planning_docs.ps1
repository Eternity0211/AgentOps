[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repositoryRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repositoryRoot

$errors = [System.Collections.Generic.List[string]]::new()

function Add-ValidationError {
    param([Parameter(Mandatory)][string]$Message)
    $errors.Add($Message)
}

$requiredFiles = @(
    'AGENTS.md',
    'README.md',
    'TODO.md',
    'docs/PROJECT_SPEC.md',
    'docs/ARCHITECTURE.md',
    'docs/DATA_MODEL.md',
    'docs/THREAT_MODEL.md',
    'docs/EVALUATION_PLAN.md',
    'docs/DECISION_HISTORY.md',
    'docs/COMPARISON_WITH_PROGRAMMING_TUTOR.md',
    'docs/ADR/README.md',
    'docs/ADR/0005-recovery-action-and-compensation-semantics.md'
)

foreach ($relativePath in $requiredFiles) {
    if (-not (Test-Path -LiteralPath $relativePath -PathType Leaf)) {
        Add-ValidationError "Required file is missing: $relativePath"
    }
}

$markdownPaths = & git ls-files --cached --others --exclude-standard -- '*.md'
if ($LASTEXITCODE -ne 0) {
    throw 'git ls-files failed while discovering Markdown files.'
}
$markdownFiles = $markdownPaths | ForEach-Object {
    Get-Item -LiteralPath (Join-Path $repositoryRoot $_)
}

$localLinkPattern = [regex]'\[[^\]]+\]\((?!https?://|mailto:|#)([^)#]+)(?:#[^)]+)?\)'
$fencePattern = [regex]'(?m)^```'
$trailingWhitespacePattern = [regex]'(?m)[ \t]+$'
$mergeConflictPattern = [regex]'(?m)^(?:<<<<<<< .+|=======|>>>>>>> .+)$'

foreach ($file in $markdownFiles) {
    $content = [System.IO.File]::ReadAllText($file.FullName)
    $displayPath = [System.IO.Path]::GetRelativePath($repositoryRoot, $file.FullName)

    if ($trailingWhitespacePattern.IsMatch($content)) {
        Add-ValidationError "Trailing whitespace found: $displayPath"
    }

    if (($fencePattern.Matches($content).Count % 2) -ne 0) {
        Add-ValidationError "Unbalanced fenced code block: $displayPath"
    }

    if ($mergeConflictPattern.IsMatch($content)) {
        Add-ValidationError "Merge-conflict marker found: $displayPath"
    }

    $bytes = [System.IO.File]::ReadAllBytes($file.FullName)
    if ($bytes.Length -eq 0 -or $bytes[-1] -ne 10 -or ($bytes.Length -gt 1 -and $bytes[-2] -eq 10)) {
        Add-ValidationError "File must end with exactly one LF: $displayPath"
    }

    foreach ($match in $localLinkPattern.Matches($content)) {
        $target = $match.Groups[1].Value.Trim('<', '>')
        $resolvedTarget = Join-Path -Path $file.DirectoryName -ChildPath $target
        if (-not (Test-Path -LiteralPath $resolvedTarget)) {
            Add-ValidationError "Broken local Markdown link in ${displayPath}: $target"
        }
    }
}

$trackedFiles = & git ls-files --cached --others --exclude-standard
if ($LASTEXITCODE -ne 0) {
    throw 'git ls-files failed.'
}

$textExtensions = @('.md', '.yml', '.yaml', '.ps1', '.py', '.toml', '.json', '.ts', '.tsx', '.js', '.jsx')
$secretPatterns = @(
    [regex]'ghp_[A-Za-z0-9]{20,}',
    [regex]'github_pat_[A-Za-z0-9_]{20,}',
    [regex]'AKIA[0-9A-Z]{16}',
    [regex]'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'
)

foreach ($relativePath in $trackedFiles) {
    $extension = [System.IO.Path]::GetExtension($relativePath).ToLowerInvariant()
    if ($extension -notin $textExtensions -and $relativePath -notin @('.gitignore', '.python-version')) {
        continue
    }

    $content = [System.IO.File]::ReadAllText((Join-Path $repositoryRoot $relativePath))
    foreach ($pattern in $secretPatterns) {
        if ($pattern.IsMatch($content)) {
            Add-ValidationError "Credential-shaped content found: $relativePath"
            break
        }
    }
}

$todoContent = [System.IO.File]::ReadAllText((Join-Path $repositoryRoot 'TODO.md'))
$requiredTerms = @(
    'Diagnosis Agent',
    'Remediation Agent',
    'Evidence Gate',
    'Tool Gateway',
    'rollback_service',
    'Ground Truth',
    'Prompt Registry',
    'LangGraph',
    'PostgreSQL',
    'pgvector',
    'Prometheus',
    'Loki',
    'Tempo',
    'Testcontainers',
    'Viewer, Operator, Approver, Admin',
    'rules-only baseline',
    'single-Agent baseline',
    'controlled LangGraph baseline',
    'Explicit non-goal guardrails'
)

foreach ($term in $requiredTerms) {
    if (-not $todoContent.Contains($term, [System.StringComparison]::OrdinalIgnoreCase)) {
        Add-ValidationError "TODO coverage term is missing: $term"
    }
}

$nonGoalMarker = '## Explicit non-goal guardrails for the core version'
$nonGoalIndex = $todoContent.IndexOf($nonGoalMarker, [System.StringComparison]::Ordinal)
if ($nonGoalIndex -lt 0) {
    Add-ValidationError 'TODO non-goal guardrail section is missing.'
} else {
    $nonGoalSection = $todoContent.Substring($nonGoalIndex)
    if ([regex]::IsMatch($nonGoalSection, '(?m)^- \[ \]')) {
        Add-ValidationError 'Non-goal guardrails must not appear as open checklist work.'
    }
}

if ($errors.Count -gt 0) {
    foreach ($validationError in $errors) {
        Write-Error $validationError
    }
    exit 1
}

Write-Host "Planning validation passed: $($markdownFiles.Count) Markdown files, $($requiredTerms.Count) coverage terms."
