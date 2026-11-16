# Make sure to use Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process

param(
    [Parameter(Mandatory = $true)]
    [string]$InputFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [Parameter(Mandatory = $true)]
    [string]$MadsPath,

    [string]$AtariMusicPath,

    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Atari Music Composer - 16-bit bass arrangement batch
# Generates one WAV and one XEX per instrument combination.
#
# IMPORTANT:
# - 16-bit bass uses the joined POKEY pair CH1+CH2.
# - Assign the 16-bit bass instrument ONLY to logical channel 1.
# - Do NOT assign an instrument to channel 2.
# - The selected 16-bit bass instruments have different MIDI ranges.

function Resolve-AtariMusicExe {
    param([string]$RequestedPath)

    if ($RequestedPath) {
        if (-not (Test-Path -LiteralPath $RequestedPath -PathType Leaf)) {
            throw "Specified atari-music executable not found: $RequestedPath"
        }
        return (Resolve-Path -LiteralPath $RequestedPath).Path
    }

    $venvCandidates = @(
        (Join-Path $PSScriptRoot ".venv\Scripts\atari-music.exe"),
        (Join-Path $PSScriptRoot ".venv/bin/atari-music")
    )
    foreach ($candidate in $venvCandidates) {
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    foreach ($cmdName in @("atari-music.exe", "atari-music")) {
        $cmd = Get-Command $cmdName -ErrorAction SilentlyContinue
        if ($cmd) {
            return $cmd.Source
        }
    }

    throw "atari-music executable not found in .venv or PATH. Activate .venv, ensure atari-music.exe is in PATH, or pass -AtariMusicPath."
}

function Invoke-AtariMusicCli {
    param(
        [string]$Executable,
        [string[]]$CliArgs
    )

    $prevPreference = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        & $Executable @CliArgs 2>&1 | ForEach-Object {
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
        Name        = "classic_16bit"
        Bass        = "bass_16bit_pure"
        Lead        = "lead_pure_sustain"
        Perc        = "perc_snare_crisp"
        Description = "Pure 16-bit bass, sustained lead, crisp snare"
    },
    @{
        Name        = "soft_pulse_16bit"
        Bass        = "bass_16bit_pure"
        Lead        = "lead_c1_octave_pulse"
        Perc        = "perc_hihat_closed"
        Description = "Pure 16-bit bass, pulsing lead, closed hi-hat"
    },
    @{
        Name        = "crystal_cavern_16bit"
        Bass        = "bass_16bit_pure"
        Lead        = "lead_pure_pluck"
        Perc        = "perc_tom_pitched"
        Description = "Pure 16-bit bass, plucked lead, pitched tom"
    },
    @{
        Name        = "heavy_dungeon_16bit"
        Bass        = "bass_16bit_poly5_growl"
        Lead        = "lead_pure_pluck"
        Perc        = "perc_tom_pitched"
        Description = "POLY5 16-bit growl bass, plucked lead, pitched tom"
    },
    @{
        Name        = "iron_ritual_16bit"
        Bass        = "bass_16bit_poly5_growl"
        Lead        = "lead_attack_bite"
        Perc        = "perc_snare_crisp"
        Description = "POLY5 16-bit growl bass, aggressive lead, snare"
    },
    @{
        Name        = "battle_march_16bit"
        Bass        = "bass_16bit_poly5_growl"
        Lead        = "lead_c1_octave_pulse"
        Perc        = "perc_kick_tight"
        Description = "POLY5 16-bit growl bass, pulsing lead, kick"
    },
    @{
        Name          = "vanilla"
        PlayerVersion = "v1"
        Description   = "Original composition instruments compiled with legacy v1 player"
    }
)

Write-Host ""
Write-Host "Atari Music Composer - 16-bit Bass Arrangement Batch" -ForegroundColor Cyan
Write-Host "----------------------------------------------------"

$atariMusicExe = Resolve-AtariMusicExe -RequestedPath $AtariMusicPath

$versionCheckExit = Invoke-AtariMusicCli -Executable $atariMusicExe -CliArgs @("--version")
if ($versionCheckExit -ne 0) {
    throw "Selected CLI ($atariMusicExe) failed '--version' check (exit code: $versionCheckExit)."
}

if (-not (Test-Path -LiteralPath $InputFile -PathType Leaf)) {
    throw "Input composition not found: $InputFile"
}

if (-not (Test-Path -LiteralPath $MadsPath -PathType Leaf)) {
    throw "MADS executable not found: $MadsPath"
}

$inputFullPath = (Resolve-Path -LiteralPath $InputFile).Path
$madsFullPath = (Resolve-Path -LiteralPath $MadsPath).Path
$outputFullPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($OutputDirectory)
$isDslInput = [System.IO.Path]::GetExtension($inputFullPath).Equals(".dsl", [System.StringComparison]::OrdinalIgnoreCase)
$arrangeInputPath = $inputFullPath
$tempConvertedJson = $null

$successCount = 0
$failedCount = 0
$skippedCount = 0

try {
    if ($isDslInput) {
        $tempConvertedJson = Join-Path ([System.IO.Path]::GetTempPath()) ("atari_music_dsl_" + [guid]::NewGuid().ToString("N") + ".json")
        Write-Host "Converting Music DSL to temporary JSON..." -ForegroundColor Cyan
        $dslExitCode = Invoke-AtariMusicCli -Executable $atariMusicExe -CliArgs @(
            "import-dsl",
            $inputFullPath,
            "--output-json", $tempConvertedJson
        )
        if ($dslExitCode -ne 0 -or -not (Test-Path -LiteralPath $tempConvertedJson -PathType Leaf)) {
            throw "Failed to convert Music DSL input '$inputFullPath' to JSON (exit code: $dslExitCode)."
        }
        $arrangeInputPath = $tempConvertedJson
    }

    # Verify that the composition (AICompositionDoc or POKEY IR IRSong) is configured for 16-bit bass.
    try {
        $composition = Get-Content -LiteralPath $arrangeInputPath -Raw |
        ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        throw "Cannot parse input JSON: $($_.Exception.Message)"
    }

    $use16BitBass = $null
    if ($null -ne $composition.hardware -and $null -ne $composition.hardware.PSObject.Properties["use_16bit_bass"]) {
        $use16BitBass = [bool]$composition.hardware.use_16bit_bass
    }
    elseif ($null -ne $composition.PSObject.Properties["uses_16bit_bass"]) {
        $use16BitBass = [bool]$composition.uses_16bit_bass
    }

    if ($use16BitBass -ne $true) {
        throw @"
This composition is not configured for 16-bit bass.
This script is intended only for compositions with:

    hardware.use_16bit_bass = true   (AI Composition JSON / DSL with 'BASS 16BIT')
    or uses_16bit_bass = true        (POKEY IR JSON)

Use the 8-bit arrangement script for compositions without 16-bit bass.
"@
    }

    New-Item -ItemType Directory -Force -Path $outputFullPath | Out-Null

    Write-Host "CLI:      $atariMusicExe"
    Write-Host "Input:    $inputFullPath$(if ($isDslInput) { ' (Music DSL -> temp JSON)' })"
    Write-Host "Output:   $outputFullPath"
    Write-Host "MADS:     $madsFullPath"
    Write-Host "Variants: $($variants.Count)"
    Write-Host "Bass mode: 16-bit CH1+CH2"
    Write-Host ""

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

        $playerVersion = if ($variant.PlayerVersion) { $variant.PlayerVersion } else { "v2" }
        $hasChannelOverrides = [bool]($variant.Bass -or $variant.Lead -or $variant.Perc)

        # CH1 owns the complete 16-bit bass pair CH1+CH2 (when arranging v2 presets).
        # CH2 is intentionally not assigned an instrument.
        $cliArgs = @(
            "arrange",
            $arrangeInputPath
        )
        if ($variant.Bass) {
            $cliArgs += @("--channel-instrument", "1=$($variant.Bass)")
        }
        if ($variant.Lead) {
            $cliArgs += @("--channel-instrument", "3=$($variant.Lead)")
        }
        if ($variant.Perc) {
            $cliArgs += @("--channel-instrument", "4=$($variant.Perc)")
        }
        if ($hasChannelOverrides) {
            $cliArgs += @("--program-change-policy", "replace")
        }
        $cliArgs += @(
            "--player-version", $playerVersion,
            "--output-wav", $wavPath,
            "-o", $xexPath,
            "--mads", $madsFullPath
        )

        Write-Host "Player:       $playerVersion"
        if ($hasChannelOverrides) {
            Write-Host "CH1+CH2 bass: $($variant.Bass)"
            Write-Host "CH3 lead:     $($variant.Lead)"
            Write-Host "CH4 perc:     $($variant.Perc)"
            Write-Host "CH2:          reserved for 16-bit bass"
        }
        else {
            Write-Host "Instruments:  original (no catalog overrides)"
        }

        $exitCode = Invoke-AtariMusicCli -Executable $atariMusicExe -CliArgs $cliArgs

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
}
finally {
    if ($tempConvertedJson -and (Test-Path -LiteralPath $tempConvertedJson)) {
        Remove-Item -LiteralPath $tempConvertedJson -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "================================================"
Write-Host "SUMMARY" -ForegroundColor Cyan
Write-Host "================================================"
Write-Host "Successful: $successCount" -ForegroundColor Green
Write-Host "Failed:     $failedCount" -ForegroundColor Red
Write-Host "Skipped:    $skippedCount" -ForegroundColor Yellow
Write-Host "Output directory: $outputFullPath"

if ($failedCount -gt 0) {
    exit 1
}

exit 0
