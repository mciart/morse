param(
    [string]$Executable = 'dist/MorseWriter/MorseWriter.exe',
    [string]$ReportPath = 'build/frozen-smoke.json',
    [ValidateRange(1, 120)][int]$TimeoutSeconds = 120
)

$ErrorActionPreference = 'Stop'
if (-not ('MorseWriterValidation.NativePaths' -as [type])) {
    Add-Type -TypeDefinition @'
using System.Runtime.InteropServices;
using System.Text;
namespace MorseWriterValidation {
    public static class NativePaths {
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
        public static extern uint GetLongPathNameW(string path, StringBuilder result, uint capacity);
    }
}
'@
}
function Resolve-SmokePath([string]$Path) {
    $absolute = [IO.Path]::GetFullPath($Path)
    $buffer = New-Object Text.StringBuilder 32768
    $length = [MorseWriterValidation.NativePaths]::GetLongPathNameW($absolute, $buffer, $buffer.Capacity)
    if ($length -eq 0 -or $length -ge $buffer.Capacity) { throw "无法规范化验收路径：$absolute" }
    return $buffer.ToString()
}
$binary = (Resolve-Path -LiteralPath $Executable -ErrorAction Stop).Path
$reportDestination = [IO.Path]::GetFullPath($ReportPath)
$temporaryParent = (Resolve-SmokePath ([IO.Path]::GetTempPath())).TrimEnd('\')
$temporaryRoot = [IO.Path]::GetFullPath((Join-Path $temporaryParent ('morsewriter-smoke-' + [guid]::NewGuid())))
if (-not $temporaryRoot.StartsWith($temporaryParent + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw '临时验收目录不在预期位置。'
}
$oldLocalAppData, $oldPublic = $env:LOCALAPPDATA, $env:PUBLIC
$process = $null
try {
    $env:LOCALAPPDATA = Join-Path $temporaryRoot 'LocalAppData'
    $env:PUBLIC = Join-Path $temporaryRoot 'Public'
    New-Item -ItemType Directory -Path $env:LOCALAPPDATA, $env:PUBLIC -Force | Out-Null
    $temporaryReport = Join-Path $temporaryRoot 'report.json'
    $process = Start-Process -FilePath $binary -ArgumentList @('--smoke-test', ('"' + $temporaryReport + '"')) `
        -WorkingDirectory $temporaryRoot -WindowStyle Hidden -PassThru
    if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
        $process.Kill()
        $process.WaitForExit()
        throw '独立程序启动验收超时。'
    }
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($reportDestination)) -Force | Out-Null
    if (Test-Path -LiteralPath $temporaryReport) {
        Copy-Item -LiteralPath $temporaryReport -Destination $reportDestination -Force
    }
    if ($process.ExitCode -ne 0) { throw "独立程序退出码：$($process.ExitCode)" }
    if (-not (Test-Path -LiteralPath $temporaryReport)) { throw '独立程序未生成验收报告。' }
    $report = Get-Content -LiteralPath $temporaryReport -Raw -Encoding utf8 | ConvertFrom-Json
    if ($report.ok -ne $true -or $report.frozen -ne $true) { throw '独立程序资源或初始化验收失败。' }
    if ($report.theme -ne 'system' -or $report.input_hooks -ne $false -or $report.startup_hidden -ne $true) {
        throw '新用户默认主题、无输入钩子或隐藏启动校验失败。'
    }
    $database = Resolve-SmokePath $report.database
    $expectedDataRoot = (Resolve-SmokePath $env:LOCALAPPDATA).TrimEnd('\') + '\'
    if (-not $database.StartsWith($expectedDataRoot, [StringComparison]::OrdinalIgnoreCase) -or
        -not (Test-Path -LiteralPath $database -PathType Leaf)) {
        throw '词库未写入隔离的用户目录。'
    }
    Write-Output "独立程序验收通过：$($report.version)，主题跟随系统，码表 $($report.guide_actions) 项。"
}
finally {
    $env:LOCALAPPDATA, $env:PUBLIC = $oldLocalAppData, $oldPublic
    if ($process) { $process.Dispose() }
    $resolvedTemporaryRoot = [IO.Path]::GetFullPath($temporaryRoot)
    if ($resolvedTemporaryRoot.StartsWith($temporaryParent + '\', [StringComparison]::OrdinalIgnoreCase) -and
        ([IO.Path]::GetFileName($resolvedTemporaryRoot) -like 'morsewriter-smoke-*') -and
        (Test-Path -LiteralPath $resolvedTemporaryRoot)) {
        Remove-Item -LiteralPath $resolvedTemporaryRoot -Recurse -Force
    }
}
