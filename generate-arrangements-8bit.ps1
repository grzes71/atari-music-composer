param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [string]$MadsPath,

    [string]$PythonPath,

    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Atari Music Composer - 8-bit arrangement batch
# Generates one WAV and one XEX per instrument combination.
# Intended only for compositions that do NOT use 16-bit bass.

function Resolve-AtariMusicPython {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "Specified Python executable not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $venvCandidates = @(
        (Join-Path $PSScriptRoot ".venv\Scripts\python.exe"),
        (Join-Path $PSScriptRoot ".venv/bin/python")
    )
    foreach ($candidate in $venvCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }

    throw "Python executable not found in .venv or PATH."
}

function Invoke-AtariMusicCli {
    param(
        [string]$PythonExe,
        [string[]]$CliArgs
    )

    $prevPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $PythonExe @CliArgs 2>&1 | ForEach-Object {
            if ($_ -is [System.Management.Automation.ErrorRecord]) {
                [Console]::Error.WriteLine($_.ToString())
            }
            else {
                Write-Host $_
            }
        }
        return $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $prevPreference
    }
}

$variants = @(
    @{
        Name = "classic_8bit"
        Bass = "bass_15khz_pure"
        Harmony = "harmony_soft_square"
        Lead = "lead_pure_sustain"
        Perc = "perc_snare_crisp"
        Description = "Clean bass, soft square harmony, sustained lead, crisp snare"
    },
    @{
        Name = "soft_pulse_8bit"
        Bass = "bass_15khz_pure"
        Harmony = "harmony_soft_square"
        Lead = "lead_c1_octave_pulse"
        Perc = "perc_hihat_closed"
        Description = "Clean bass, soft square harmony, pulsing lead, closed hi-hat"
    },
    @{
        Name = "heavy_dungeon_8bit"
        Bass = "bass_poly4_punch"
        Harmony = "harmony_soft_square"
        Lead = "lead_pure_pluck"
        Perc = "perc_tom_pitched"
        Description = "Punchy bass, soft square harmony, plucked lead, pitched tom"
    },
    @{
        Name = "iron_ritual_8bit"
        Bass = "bass_poly4_punch"
        Harmony = "harmony_soft_square"
        Lead = "lead_attack_bite"
        Perc = "perc_snare_crisp"
        Description = "Punchy bass, soft square harmony, aggressive lead, snare"
    },
    @{
        Name = "haunted_forest_8bit"
        Bass = "bass_15khz_pure"
        Harmony = "harmony_soft_square"
        Lead = "lead_buzz_steady"
        Perc = "perc_hihat_closed"
        Description = "Clean bass, soft square harmony, buzzing lead, subtle hi-hat"
    },
    @{
        Name = "battle_march_8bit"
        Bass = "bass_poly4_punch"
        Harmony = "harmony_soft_square"
        Lead = "lead_c1_octave_pulse"
        Perc = "perc_kick_tight"
        Description = "Punchy bass, soft square harmony, pulsing lead, kick"
    }
)

Write-Host ""
Write-Host "Atari Music Composer - Arrangement Batch" -ForegroundColor Cyan
Write-Host "----------------------------------------"

$pythonExe = Resolve-AtariMusicPython -RequestedPath $PythonPath

$importCheckExit = Invoke-AtariMusicCli -PythonExe $pythonExe -CliArgs @("-c", "import atari_music")
if ($importCheckExit -ne 0) {
    throw "Selected Python ($pythonExe) cannot import 'atari_music'. Activate .venv or pass -PythonPath."
}

if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
    throw "Input composition not found: $InputFile"
}

if (-not (Test-Path -LiteralPath $MadsPath -PathType Leaf)) {
    throw "MADS executable not found: $MadsPath"
}

$inputFullPath = (Resolve-Path -LiteralPath $InputFile).Path
$madsFullPath = (Resolve-Path -LiteralPath $MadsPath).Path
$outputFullPath = [System.IO.Path]::GetFullPath($OutputDirectory)

# Verify that the input is a JSON composition (AICompositionDoc or POKEY IR IRSong) and does NOT use 16-bit bass.
try {
    $composition = Get-Content -LiteralPath $inputFullPath -Raw |
        ConvertFrom-Json -ErrorAction Stop
}
catch {
    if ([System.IO.Path]::GetExtension($inputFullPath).Equals(".dsl", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Music DSL files must be converted to JSON first: python -m atari_music import-dsl `"$inputFullPath`" --output-json composition.json"
    }
    throw "Cannot parse input JSON: $($_.Exception.Message)"
}

$use16BitBass = $null
if ($null -ne $composition.hardware -and $null -ne $composition.hardware.PSObject.Properties["use_16bit_bass"]) {
    $use16BitBass = [bool]$composition.hardware.use_16bit_bass
}
elseif ($null -ne $composition.PSObject.Properties["uses_16bit_bass"]) {
    $use16BitBass = [bool]$composition.uses_16bit_bass
}

if ($use16BitBass -eq $true) {
    throw @"
This composition uses 16-bit bass.
This script is intended only for compositions with 8-bit bass.

Do not simply change hardware.use_16bit_bass to false unless the
composition has actually been prepared for independent 8-bit playback.
"@
}

if ($null -eq $use16BitBass) {
    Write-Warning "Neither hardware.use_16bit_bass nor uses_16bit_bass is defined. Verify the composition manually."
}

New-Item -ItemType Directory -Force -Path $outputFullPath | Out-Null

Write-Host "Python:   $pythonExe"
Write-Host "Input:    $inputFullPath"
Write-Host "Output:   $outputFullPath"
Write-Host "MADS:     $madsFullPath"
Write-Host "Variants: $($variants.Count)"
Write-Host ""

$successCount = 0
$failedCount = 0
$skippedCount = 0

foreach ($variant in $variants) {
    $name = $variant.Name
    $wavPath = Join-Path $outputFullPath "$name.wav"
    $xexPath = Join-Path $outputFullPath "$name.xex"

    Write-Host ""
    Write-Host "[$name]" -ForegroundColor Cyan
    Write-Host $variant.Description -ForegroundColor DarkGray

    if (-not $Force -and (
        (Test-Path -LiteralPath $wavPath) -or
        (Test-Path -LiteralPath $xexPath)
    )) {
        Write-Warning "Output already exists. Skipping (use -Force to overwrite)."
        $skippedCount++
        continue
    }

    $cliArgs = @(
        "-m", "atari_music",
        "arrange",
        $inputFullPath,
        "--channel-instrument", "1=$($variant.Bass)",
        "--channel-instrument", "2=$($variant.Harmony)",
        "--channel-instrument", "3=$($variant.Lead)",
        "--channel-instrument", "4=$($variant.Perc)",
        "--program-change-policy", "replace",
        "--player-version", "v2",
        "--output-wav", $wavPath,
        "-o", $xexPath,
        "--mads", $madsFullPath
    )

    Write-Host "CH1 Bass:    $($variant.Bass)"
    Write-Host "CH2 Harmony: $($variant.Harmony)"
    Write-Host "CH3 Lead:    $($variant.Lead)"
    Write-Host "CH4 Perc:    $($variant.Perc)"

    $exitCode = Invoke-AtariMusicCli -PythonExe $pythonExe -CliArgs $cliArgs

    if ($exitCode -ne 0) {
        Write-Host "FAILED (exit code: $exitCode)" -ForegroundColor Red
        $failedCount++
        continue
    }

    $wavOk = (Test-Path -LiteralPath $wavPath -PathType Leaf) -and ((Get-Item -LiteralPath $wavPath).Length -gt 0)
    $xexOk = (Test-Path -LiteralPath $xexPath -PathType Leaf) -and ((Get-Item -LiteralPath $xexPath).Length -gt 0)

    if ($wavOk -and $xexOk) {
        Write-Host "OK - WAV and XEX generated." -ForegroundColor Green
        $successCount++
    }
    else {
        Write-Host "FAILED - expected non-empty WAV and XEX output files." -ForegroundColor Red
        $failedCount++
    }
}

Write-Host ""
Write-Host "========================================"
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "========================================"
Write-Host "Successful: $successCount" -ForegroundColor Green
Write-Host "Failed:     $failedCount" -ForegroundColor Red
Write-Host "Skipped:    $skippedCount" -ForegroundColor Yellow
Write-Host "Output directory: $outputFullPath"

if ($failedCount -gt 0) {
    exit 1
}

exit 0
