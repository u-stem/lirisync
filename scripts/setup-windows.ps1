<#
.SYNOPSIS
Sets up a Windows development machine for Lirisync in one run.

.DESCRIPTION
Installs missing tools with winget (uv, bun, ffmpeg), installs the locked
dependencies, and downloads the models used by the manual tests and the
evaluation tools. Safe to run again: installed tools are skipped and the model
fetch tools skip files whose SHA-256 already matches. No administrator rights
are needed.

.PARAMETER ModelsDir
Where to put the models. The separation model goes to <ModelsDir>\separator and
the character CTC model goes to <ModelsDir>\aligner.

.PARAMETER SkipTools
Do not use winget. The tools must already be on PATH.

.PARAMETER SkipModels
Do not download the models.

.EXAMPLE
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
#>
[CmdletBinding()]
param(
    [string]$ModelsDir = 'C:\lirisync-models',
    [switch]$SkipTools,
    [switch]$SkipModels
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# Tools that must be on PATH: command name -> winget package id.
# git is not installed here: run this script from a clone of the repository.
$RequiredTools = [ordered]@{
    uv     = 'astral-sh.uv'
    bun    = 'Oven-sh.Bun'
    ffmpeg = 'Gyan.FFmpeg'
}

$RepoRoot = Split-Path -Parent $PSScriptRoot

function Write-Step {
    param([string]$Message)
    Write-Host ''
    Write-Host "==> $Message"
}

function Test-CommandExists {
    param([string]$Name)
    return [bool](Get-Command -Name $Name -CommandType Application -ErrorAction SilentlyContinue)
}

# Runs an external command and stops with a clear message on a non-zero exit code.
# Does not rely on $PSNativeCommandUseErrorActionPreference (PowerShell 7 only).
function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$Description,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [string[]]$Arguments = @()
    )
    $global:LASTEXITCODE = 0
    # Windows PowerShell 5.1 turns native stderr output into errors under 'Stop',
    # and tools such as uv and bun write progress to stderr.
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($exitCode -ne 0) {
        throw "Step failed: $Description (exit code $exitCode)"
    }
}

# Re-reads PATH from the registry (Machine and User) so tools installed by winget
# can be used in this session. Entries already in this session are kept at the end.
function Update-SessionPath {
    $machine = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $user = [Environment]::GetEnvironmentVariable('Path', 'User')
    $seen = @{}
    $entries = @()
    foreach ($source in @($machine, $user, $env:Path)) {
        if (-not $source) { continue }
        foreach ($entry in $source.Split(';')) {
            $trimmed = $entry.Trim()
            if ($trimmed -and -not $seen.ContainsKey($trimmed.ToLowerInvariant())) {
                $seen[$trimmed.ToLowerInvariant()] = $true
                $entries += $trimmed
            }
        }
    }
    $env:Path = $entries -join ';'
}

function Install-MissingTools {
    # A tool installed earlier from a window opened before the install is on the
    # registry PATH but not on this session's; winget would refuse it as installed.
    Update-SessionPath
    $missing =@($RequiredTools.Keys | Where-Object { -not (Test-CommandExists $_) })
    if ($missing.Count -eq 0) {
        Write-Host 'All tools are already installed.'
        return
    }

    if (-not (Test-CommandExists 'winget')) {
        throw ('winget was not found. Update "App Installer" in the Microsoft Store, ' +
            'then run this script again. Missing tools: ' + ($missing -join ', '))
    }

    foreach ($name in $missing) {
        $id = $RequiredTools[$name]
        Write-Host "Installing $name ($id)"
        Invoke-Native -Description "winget install $id" -FilePath 'winget' -Arguments @(
            'install', '--id', $id, '-e',
            '--accept-source-agreements', '--accept-package-agreements'
        )
    }

    Update-SessionPath

    $stillMissing = @($missing | Where-Object { -not (Test-CommandExists $_) })
    if ($stillMissing.Count -gt 0) {
        throw ('Installed, but not found on PATH in this session: ' + ($stillMissing -join ', ') +
            '. Open a new PowerShell window and run this script again.')
    }
}

function Get-ToolVersion {
    param([string]$Name)
    $versionArgs = @('--version')
    if ($Name -eq 'ffmpeg') { $versionArgs = @('-version') }
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $lines = @(& $Name @versionArgs 2>&1 | ForEach-Object { "$_" })
    }
    finally {
        $ErrorActionPreference = $previous
    }
    if ($lines.Count -eq 0) { return '(no version output)' }
    return $lines[0]
}

# Resolve against the caller's current directory; the fetch tools run elsewhere
# (uv --directory), so they need an absolute path.
$ModelsRoot = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($ModelsDir)
$SeparatorDir = Join-Path $ModelsRoot 'separator'
$AlignerDir = Join-Path $ModelsRoot 'aligner'

Push-Location $RepoRoot
try {
    if ($SkipTools) {
        Write-Step 'Skipping tool installation (-SkipTools)'
    }
    else {
        Write-Step 'Installing missing tools with winget'
        Install-MissingTools
    }

    Write-Step 'Installing TypeScript dependencies (bun)'
    Invoke-Native -Description 'bun install' -FilePath 'bun' -Arguments @('install', '--frozen-lockfile')

    Write-Step 'Installing align worker dependencies (uv)'
    Invoke-Native -Description 'uv sync (workers/align)' -FilePath 'uv' -Arguments @(
        '--directory', 'workers/align', 'sync', '--locked'
    )

    Write-Step 'Installing evaluation tool dependencies (uv)'
    Invoke-Native -Description 'uv sync (eval/transcribe)' -FilePath 'uv' -Arguments @(
        '--directory', 'eval/transcribe', 'sync', '--locked'
    )

    if ($SkipModels) {
        Write-Step 'Skipping model download (-SkipModels)'
    }
    else {
        Write-Step "Fetching the separation model into $SeparatorDir"
        Invoke-Native -Description 'fetch_separator_model.py' -FilePath 'uv' -Arguments @(
            '--directory', 'workers/align', 'run', 'python', 'tools/fetch_separator_model.py',
            '--dest', $SeparatorDir
        )

        Write-Step "Fetching the character CTC model into $AlignerDir"
        Invoke-Native -Description 'fetch_aligner_model.py' -FilePath 'uv' -Arguments @(
            '--directory', 'workers/align', 'run', 'python', 'tools/fetch_aligner_model.py',
            '--dest', $AlignerDir
        )
    }

    Write-Step 'Summary'
    foreach ($name in @('git') + @($RequiredTools.Keys)) {
        if (Test-CommandExists $name) {
            Write-Host ("{0,-7} {1}" -f $name, (Get-ToolVersion $name))
        }
    }
    if ($SkipModels) {
        Write-Host 'Models: skipped'
    }
    else {
        Write-Host "Separation model: $SeparatorDir"
        Write-Host "Aligner model:    $AlignerDir"
    }
    Write-Host ''
    Write-Host 'Next: read the first section of eval/README.md, which explains how to place songs.'
}
finally {
    Pop-Location
}
