# Builds dist\EyeToyStudio.exe : un fichier unique, sans dependance externe.
#
#   .\build.ps1
#
# Etapes : tests unitaires, fichier de version, signature optionnelle de
# l'installeur de pilote, PyInstaller, signature optionnelle du binaire, puis
# lancement du binaire hors du projet pour lire son rapport de sante.
#
# Signature : definir EYETOY_SIGN_THUMBPRINT avec l'empreinte SHA-1 d'un
# certificat de signature de code installe dans le magasin de l'utilisateur.
# signtool.exe (Windows SDK) est alors cherche automatiquement. Sans cette
# variable, le binaire n'est pas signe et SmartScreen avertira a l'ouverture.
#
# La DLL libusb doit atterrir dans un sous-dossier usb1\ du bundle, car c'est
# la que le paquet usb1 la cherche au chargement.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$python = ".venv\Scripts\python.exe"
$dll = ".venv\Lib\site-packages\usb1\libusb-1.0.dll"
$wdi = "vendor\wdi-simple.exe"
$icon = "assets\eyetoy.ico"
foreach ($required in @($python, $dll, $wdi, $icon)) {
    if (-not (Test-Path $required)) {
        throw "introuvable : $required  (pip install -r requirements-dev.txt, voir aussi vendor\README.md et tools\make_icon.py)"
    }
}

# -- tests ---------------------------------------------------------------------
& $python -m unittest discover -s tests -t .
if ($LASTEXITCODE -ne 0) { throw "tests en echec, construction annulee" }

# -- version -------------------------------------------------------------------
$version = (& $python -c "import eyetoy; print(eyetoy.__version__)").Trim()
$parts = @($version.Split(".") | ForEach-Object { [int]$_ })
while ($parts.Count -lt 4) { $parts += 0 }
$tuple = $parts -join ", "
New-Item -ItemType Directory -Force build | Out-Null
$versionFile = "build\version_info.txt"
@"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($tuple),
    prodvers=($tuple),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
    ),
  kids=[
    StringFileInfo(
      [
      StringTable(
        '040c04b0',
        [StringStruct('CompanyName', 'EyeToy Studio'),
        StringStruct('FileDescription', 'EyeToy Studio - camera EyeToy PS2 sous Windows'),
        StringStruct('FileVersion', '$version'),
        StringStruct('InternalName', 'EyeToyStudio'),
        StringStruct('LegalCopyright', 'GPL-2.0'),
        StringStruct('OriginalFilename', 'EyeToyStudio.exe'),
        StringStruct('ProductName', 'EyeToy Studio'),
        StringStruct('ProductVersion', '$version')])
      ]),
    VarFileInfo([VarStruct('Translation', [0x040c, 1200])])
  ]
)
"@ | Set-Content -Encoding UTF8 $versionFile

# -- signature (optionnelle) ---------------------------------------------------
$thumbprint = $env:EYETOY_SIGN_THUMBPRINT
$signtool = $null
if ($thumbprint) {
    $signtool = Get-ChildItem "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe" `
                    -ErrorAction SilentlyContinue |
                Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $signtool) { throw "EYETOY_SIGN_THUMBPRINT est defini mais signtool.exe est introuvable (Windows SDK)" }
}

function Sign-File([string]$path) {
    & $signtool.FullName sign /sha1 $thumbprint /fd sha256 `
        /tr http://timestamp.digicert.com /td sha256 /q $path
    if ($LASTEXITCODE -ne 0) { throw "signature en echec : $path" }
}

# The installer runs elevated, so it is the one SmartScreen and Smart App
# Control look at hardest: sign the copy that goes into the bundle.
if ($signtool) {
    New-Item -ItemType Directory -Force build\vendor | Out-Null
    Copy-Item $wdi build\vendor\wdi-simple.exe -Force
    $wdi = "build\vendor\wdi-simple.exe"
    Sign-File $wdi
}

# -- build ---------------------------------------------------------------------
.\.venv\Scripts\pyinstaller.exe `
    --onefile `
    --windowed `
    --name EyeToyStudio `
    --icon $icon `
    --version-file $versionFile `
    --add-binary "$dll;usb1" `
    --add-binary "$wdi;vendor" `
    --add-data "$icon;assets" `
    --noconfirm `
    --clean `
    app.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller a echoue" }

$exe = Get-Item dist\EyeToyStudio.exe
if ($signtool) { Sign-File $exe.FullName }
"{0} - {1:N1} Mo - version {2}{3}" -f $exe.FullName, ($exe.Length / 1MB), $version,
    ($(if ($signtool) { " - signe" } else { " - non signe" }))

# -- verification --------------------------------------------------------------
# Lance le binaire hors du projet et lit son rapport de sante. Les captures de
# l'auto-test vont dans ce dossier temporaire, pas dans les Images de
# l'utilisateur, et l'auto-test n'enregistre pas les reglages.
$probe = Join-Path $env:TEMP "eyetoy-build-check"
Remove-Item -Recurse -Force $probe -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $probe | Out-Null
Copy-Item $exe.FullName $probe

$env:EYETOY_SMOKE = Join-Path $probe "report.json"
$env:EYETOY_SMOKE_SECONDS = "8"
$env:EYETOY_CAPTURES = Join-Path $probe "captures"
try {
    $proc = Start-Process -FilePath (Join-Path $probe "EyeToyStudio.exe") `
                          -WorkingDirectory $probe -PassThru
    if (-not $proc.WaitForExit(60000)) {
        $proc.Kill()
        Write-Warning "le binaire ne s'est pas ferme dans les 60 s"
    }
} finally {
    Remove-Item Env:\EYETOY_SMOKE, Env:\EYETOY_SMOKE_SECONDS, Env:\EYETOY_CAPTURES
}

$report = Join-Path $probe "report.json"
if (Test-Path $report) {
    Get-Content $report
} else {
    Write-Warning "pas de rapport : voir %LOCALAPPDATA%\EyeToyStudio\eyetoy.log"
}
