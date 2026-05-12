param(
    [switch]$Clean,
    [switch]$OneFile
)
$ErrorActionPreference = "Stop"

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..\")).Path
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Entry = Join-Path $Repo "powerflow_builder\citl_work_ticketing_gui.py"
$Dist = Join-Path $Repo "powerflow_builder\\dist"
$Work = Join-Path $Repo "powerflow_builder\\build"
$Name = "CITL Ticketing Automation GUI"

if (!(Test-Path -LiteralPath $Py)) {
    throw "Python venv not found at $Py"
}
if (!(Test-Path -LiteralPath $Entry)) {
    throw "Entry script not found at $Entry"
}

$BasePy = (& $Py -c "import sys; print(sys.base_prefix)").Trim()
$TclDir = Join-Path $BasePy "tcl\\tcl8.6"
$TkDir = Join-Path $BasePy "tcl\\tk8.6"
$TclModuleDir = Join-Path $BasePy "tcl\\tcl8"
$DllDir = Join-Path $BasePy "DLLs"
$TclDll = Join-Path $DllDir "tcl86t.dll"
$TkDll = Join-Path $DllDir "tk86t.dll"
if (!(Test-Path $TclDir) -or !(Test-Path $TkDir)) {
    throw "Tcl/Tk runtime directories were not found under $BasePy"
}
if (!(Test-Path $TclDll) -or !(Test-Path $TkDll)) {
    throw "Tcl/Tk runtime DLLs were not found under $DllDir"
}

if (Test-Path $TclDir) { $env:TCL_LIBRARY = $TclDir }
if (Test-Path $TkDir) { $env:TK_LIBRARY = $TkDir }

if ($Clean) {
    if (Test-Path (Join-Path $Dist $Name)) { Remove-Item -Recurse -Force (Join-Path $Dist $Name) }
    if (Test-Path (Join-Path $Work $Name)) { Remove-Item -Recurse -Force (Join-Path $Work $Name) }
}

$args = @(
    "-m", "PyInstaller",
    "--noconfirm",
    "--clean",
    "--windowed",
    "--name", $Name,
    "--distpath", $Dist,
    "--workpath", $Work,
    "--additional-hooks-dir", (Join-Path $Repo "powerflow_builder\\pyi_hooks"),
    "--hidden-import", "tkinter",
    "--hidden-import", "tkinter.ttk",
    "--hidden-import", "tkinter.scrolledtext",
    "--hidden-import", "tkinter.messagebox",
    "--hidden-import", "_tkinter",
    "--hidden-import", "powerflow_builder.flowfx_compiler",
    "--hidden-import", "powerflow_builder.flowfx_validator_pack",
    "--hidden-import", "powerflow_builder.ops_assistant",
    "--add-data", "$TclDir;_tcl_data",
    "--add-data", "$TkDir;_tk_data",
    "--add-data", "$TclModuleDir;tcl8",
    "--add-binary", "$TclDll;.",
    "--add-binary", "$TkDll;.",
    $Entry
)

if ($OneFile) {
    $args = @(
        "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", $Name, "--distpath", $Dist, "--workpath", $Work,
        "--additional-hooks-dir", (Join-Path $Repo "powerflow_builder\\pyi_hooks"),
        "--hidden-import", "tkinter", "--hidden-import", "tkinter.ttk",
        "--hidden-import", "tkinter.scrolledtext", "--hidden-import", "tkinter.messagebox",
        "--hidden-import", "_tkinter",
        "--hidden-import", "powerflow_builder.flowfx_compiler",
        "--hidden-import", "powerflow_builder.flowfx_validator_pack",
        "--hidden-import", "powerflow_builder.ops_assistant",
        "--add-data", "$TclDir;_tcl_data", "--add-data", "$TkDir;_tk_data",
        "--add-data", "$TclModuleDir;tcl8",
        "--add-binary", "$TclDll;.", "--add-binary", "$TkDll;.",
        $Entry
    )
}

Set-Location $Repo
& $Py @args

$exePath = Join-Path $Dist "$Name\$Name.exe"
if ($OneFile) {
    $exePath = Join-Path $Dist "$Name.exe"
}
if (Test-Path -LiteralPath $exePath) {
    Write-Host "Build complete: $exePath" -ForegroundColor Green
} else {
    Write-Warning "Build finished but expected executable path not found: $exePath"
}
