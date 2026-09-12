param()

$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$toolsRoot = Join-Path $projectRoot 'build\tools'
$compilerRoot = Join-Path $toolsRoot 'inno-setup-6.7.3'
$compiler = Join-Path $compilerRoot 'ISCC.exe'
if (Test-Path -LiteralPath $compiler) {
    Write-Output $compiler
    exit 0
}

# Official, pinned release. Portable mode disables uninstall registration,
# file associations and shortcuts; no global compiler installation is made.
$downloadUrl = 'https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe'
$expectedHash = '9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732'
New-Item -ItemType Directory -Force -Path $toolsRoot | Out-Null
$download = Join-Path $toolsRoot 'innosetup-6.7.3.exe'
if (-not (Test-Path -LiteralPath $download)) {
    Invoke-WebRequest -Uri $downloadUrl -OutFile $download
}
if ((Get-FileHash -LiteralPath $download -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'Inno Setup 下载文件的 SHA256 不匹配。请检查 build\tools 中的下载文件。'
}
$setupArguments = @(
    '/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', '/SP-',
    '/CURRENTUSER', '/PORTABLE=1', "/DIR=`"$compilerRoot`"",
    "/LOG=`"$(Join-Path $toolsRoot 'inno-portable.log')`""
)
$process = Start-Process -FilePath $download -ArgumentList $setupArguments -WindowStyle Hidden -Wait -PassThru
if ($process.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $compiler)) {
    throw "Inno Setup 便携解包失败，退出码 $($process.ExitCode)。"
}
Write-Output $compiler
