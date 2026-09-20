[CmdletBinding()]
param(
    [string]$Recording = "",
    [string]$NarrationScript = "",
    [string]$Output = "",
    [string]$Voice = "Microsoft Zira"
)

$ErrorActionPreference = "Stop"

# Keep all generated speech and media local to this Windows machine.
$repositoryRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($Recording)) {
    $Recording = Join-Path $repositoryRoot "artifacts\recordings\live-demo-20260920T095515Z\LicenceIQ-Live-Demo-5m13.mp4"
}
if ([string]::IsNullOrWhiteSpace($NarrationScript)) {
    $NarrationScript = Join-Path $repositoryRoot "docs\DEMO_SCRIPT.md"
}
if ([string]::IsNullOrWhiteSpace($Output)) {
    $Output = Join-Path $repositoryRoot "artifacts\recordings\live-demo-20260920T095515Z\LicenceIQ-Live-Demo-Narrated.mp4"
}

$recordingPath = [System.IO.Path]::GetFullPath($Recording)
$scriptPath = [System.IO.Path]::GetFullPath($NarrationScript)
$outputPath = [System.IO.Path]::GetFullPath($Output)
if (-not (Test-Path -LiteralPath $recordingPath -PathType Leaf)) {
    throw "The source recording was not found."
}
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) {
    throw "The narration script was not found."
}
if (Test-Path -LiteralPath $outputPath) {
    throw "Refusing to overwrite an existing final video."
}

$ffmpegCandidate = Get-ChildItem -Path (Join-Path $repositoryRoot ".tools\media\imageio_ffmpeg\binaries") -Filter "ffmpeg-*.exe" -File | Select-Object -First 1
if ($null -eq $ffmpegCandidate) {
    throw "The workspace-local FFmpeg runtime is unavailable."
}
$ffmpeg = $ffmpegCandidate.FullName

function Convert-ToSeconds {
    param([string]$Timestamp)
    $parts = $Timestamp.Split(":")
    return ([int]$parts[0] * 60) + [int]$parts[1]
}

function Get-MediaDuration {
    param([string]$Path)
    $inspection = & $ffmpeg "-hide_banner" "-i" $Path 2>&1
    $text = [string]::Join("`n", $inspection)
    $match = [regex]::Match($text, "Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
    if (-not $match.Success) {
        throw "Could not determine a media duration."
    }
    return ([int]$match.Groups[1].Value * 3600) + ([int]$match.Groups[2].Value * 60) + [double]$match.Groups[3].Value
}

function Get-ATempoFilters {
    param([double]$Tempo)
    if ($Tempo -le 0) {
        throw "Audio tempo must be positive."
    }
    $factors = New-Object System.Collections.Generic.List[double]
    while ($Tempo -lt 0.5) {
        $factors.Add(0.5)
        $Tempo = $Tempo / 0.5
    }
    while ($Tempo -gt 2.0) {
        $factors.Add(2.0)
        $Tempo = $Tempo / 2.0
    }
    $factors.Add($Tempo)
    return (($factors | ForEach-Object { "atempo=$($_.ToString('0.000000', [System.Globalization.CultureInfo]::InvariantCulture))" }) -join ",")
}

function Invoke-FFmpeg {
    param([string[]]$Arguments)
    & $ffmpeg @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "A local media-processing command failed."
    }
}

function Convert-ToSpeechText {
    param([string]$Text)
    # These substitutions improve the built-in voice's pronunciation; they do
    # not change the written narration reviewed in docs/DEMO_SCRIPT.md.
    return $Text `
        -replace "LicenceIQ", "Licence I Q" `
        -replace "Argon2", "Argon two" `
        -replace "JWT", "J W T" `
        -replace "MinIO", "Min I O" `
        -replace "pgvector", "P G vector" `
        -replace "Q-and-A", "questions and answers"
}

$sections = New-Object System.Collections.Generic.List[object]
$current = $null
foreach ($line in Get-Content -LiteralPath $scriptPath) {
    $heading = [regex]::Match($line, "^### (\d+:\d+)–(\d+:\d+) —")
    if ($heading.Success) {
        if ($null -ne $current) {
            $sections.Add($current)
        }
        $current = [pscustomobject]@{
            Start = Convert-ToSeconds $heading.Groups[1].Value
            End = Convert-ToSeconds $heading.Groups[2].Value
            Lines = New-Object System.Collections.Generic.List[string]
        }
        continue
    }
    if ($null -ne $current -and $line.StartsWith("> ")) {
        $current.Lines.Add($line.Substring(2).Trim())
    }
}
if ($null -ne $current) {
    $sections.Add($current)
}
if ($sections.Count -eq 0 -or ($sections | Where-Object { $_.Lines.Count -eq 0 }).Count -gt 0) {
    throw "The narration script does not contain complete timestamped spoken sections."
}

Add-Type -AssemblyName System.Speech
$speaker = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $speaker.SelectVoice($Voice)
    # A slightly slower local delivery leaves the final tempo correction subtle.
    $speaker.Rate = -1
    $workspace = Join-Path ([System.IO.Path]::GetDirectoryName($outputPath)) "local-narration-work"
    if (Test-Path -LiteralPath $workspace) {
        throw "The local narration work directory already exists. Choose a new output name."
    }
    New-Item -ItemType Directory -Path $workspace | Out-Null
    $timedSegments = New-Object System.Collections.Generic.List[string]

    for ($index = 0; $index -lt $sections.Count; $index++) {
        $section = $sections[$index]
        $number = ($index + 1).ToString("00")
        $rawPath = Join-Path $workspace "segment-$number-raw.wav"
        $timedPath = Join-Path $workspace "segment-$number-timed.wav"
        $spokenText = Convert-ToSpeechText ($section.Lines -join " ")
        $speaker.SetOutputToWaveFile($rawPath)
        $speaker.Speak($spokenText)
        $speaker.SetOutputToNull()

        $sourceDuration = Get-MediaDuration $rawPath
        $targetDuration = [double]($section.End - $section.Start)
        $tempo = $sourceDuration / $targetDuration
        Invoke-FFmpeg @(
            "-y", "-loglevel", "error", "-i", $rawPath,
            "-filter:a", (Get-ATempoFilters $tempo),
            "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le",
            "-t", $targetDuration.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture),
            $timedPath
        )
        $timedSegments.Add($timedPath)
    }

    $concatList = Join-Path $workspace "segments.txt"
    $concatRows = $timedSegments | ForEach-Object { "file '$($_.Replace('\', '/'))'" }
    Set-Content -LiteralPath $concatList -Value $concatRows -Encoding ascii
    $masterAudio = Join-Path $workspace "LicenceIQ-Narration-Master.m4a"
    Invoke-FFmpeg @(
        "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", $concatList,
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2", $masterAudio
    )

    $videoDuration = Get-MediaDuration $recordingPath
    Invoke-FFmpeg @(
        "-y", "-loglevel", "error", "-i", $recordingPath, "-i", $masterAudio,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-fps_mode", "passthrough",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
        "-t", $videoDuration.ToString("0.000", [System.Globalization.CultureInfo]::InvariantCulture),
        "-movflags", "+faststart", $outputPath
    )
    Invoke-FFmpeg @("-v", "error", "-i", $outputPath, "-f", "null", "NUL")
    Write-Host "Created narrated video: $outputPath"
    Write-Host "Video duration: $($videoDuration.ToString('0.0', [System.Globalization.CultureInfo]::InvariantCulture)) seconds"
} finally {
    $speaker.Dispose()
}
