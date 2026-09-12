param(
    [Alias('PythonExecutable')][string]$Python,
    [Alias('ISCCPath')][string]$Iscc,
    [switch]$BootstrapCompiler,
    [switch]$SkipTests,
    [switch]$InstallerOnly,
    [switch]$SkipInstaller
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$projectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$distribution = [IO.Path]::GetFullPath((Join-Path $projectRoot 'dist'))
$workDirectory = [IO.Path]::GetFullPath((Join-Path $projectRoot 'build\pyinstaller'))
# PyInstaller owns only these project-contained output directories. It may
# replace dist\MorseWriter on rebuild; other releases and user data are kept.
foreach ($buildPath in @($distribution, $workDirectory)) {
    if (-not $buildPath.StartsWith($projectRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "构建目录不在项目内：$buildPath"
    }
}
if (-not $Python) {
    $venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
    $Python = if (Test-Path -LiteralPath $venvPython) { $venvPython } else { (Get-Command python -ErrorAction Stop).Source }
}
Push-Location -LiteralPath $projectRoot
try {
    & $Python -c "import struct, sys; sys.exit(0 if sys.platform == 'win32' and struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw '请使用 Windows x64 Python 构建安装包。' }
    $version = (& $Python 'tools/build_release.py' '--version').Trim()
    if ($LASTEXITCODE -ne 0) { throw '读取版本号失败。' }
    $env:APP_VERSION = $version
    & $Python 'tools/build_release.py'
    if ($LASTEXITCODE -ne 0) { throw '发布资源清单校验失败。' }
    if (-not $SkipTests) {
        & $Python -m unittest discover -s tests -v
        if ($LASTEXITCODE -ne 0) { throw '回归测试失败，未生成发布包。' }
    }
    if (-not $InstallerOnly) {
        & $Python -m PyInstaller --noconfirm --clean --workpath $workDirectory --distpath $distribution 'MorseCodeGUI.spec'
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller 构建失败。' }
    }
    & $Python 'tools/build_release.py' '--check-bundle' (Join-Path $distribution 'MorseWriter')
    if ($LASTEXITCODE -ne 0) { throw '安装包资源检查失败。' }
    if ($SkipInstaller) { return }
    if (-not $Iscc) {
        $localCompiler = Join-Path $projectRoot 'build\tools\inno-setup-6.7.3\ISCC.exe'
        $compilerCandidates = @(
            $localCompiler,
            (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
            (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe')
        )
        $Iscc = $compilerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
        if (-not $Iscc) {
            $command = Get-Command iscc -ErrorAction SilentlyContinue
            if ($command) { $Iscc = $command.Source }
        }
        if (-not $Iscc -and $BootstrapCompiler) {
            $Iscc = & (Join-Path $projectRoot 'tools/get_inno_setup.ps1')
        }
    }
    if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc)) {
        throw '找不到 Inno Setup。使用 -BootstrapCompiler 解包官方便携编译器，或用 -Iscc 指定 ISCC.exe。'
    }
    & $Iscc "/DAPP_VERSION=$version" 'MorseWriterInstaller.iss'
    if ($LASTEXITCODE -ne 0) { throw 'Inno Setup 构建失败。' }
    $installer = Join-Path $distribution "MorseWriter-Setup-v$version-x64.exe"
    if (-not (Test-Path -LiteralPath $installer)) { throw '未找到预期安装包。' }
    $hash = (Get-FileHash -LiteralPath $installer -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash *$([IO.Path]::GetFileName($installer))" | Set-Content -LiteralPath "$installer.sha256" -Encoding ascii
    "$hash *$([IO.Path]::GetFileName($installer))" | Set-Content -LiteralPath (Join-Path $distribution 'SHA256SUMS') -Encoding ascii
    Write-Output "安装包：$installer"
    Write-Output "SHA256：$hash"
}
finally {
    Pop-Location
}
