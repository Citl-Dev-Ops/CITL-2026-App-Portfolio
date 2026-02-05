param(
  [string]$OllamaHost = "http://127.0.0.1:11434",
  [switch]$Portable
)
& "$PSScriptRoot\run_citl_factbook_gui_preflight.ps1" -OllamaHost $OllamaHost -Portable:$Portable
