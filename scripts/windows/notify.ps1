param(
    [ValidateSet('Info','Warn','Error','Success')][string]$Type = 'Info',
    [string]$Message = '',
    [string]$Title = 'CITL Notification'
)

Add-Type -AssemblyName System.Windows.Forms

switch ($Type) {
    'Info'    { $icon = [System.Windows.Forms.MessageBoxIcon]::Information }
    'Warn'    { $icon = [System.Windows.Forms.MessageBoxIcon]::Warning }
    'Error'   { $icon = [System.Windows.Forms.MessageBoxIcon]::Error }
    'Success' { $icon = [System.Windows.Forms.MessageBoxIcon]::Information }
    default   { $icon = [System.Windows.Forms.MessageBoxIcon]::Information }
}

[System.Windows.Forms.MessageBox]::Show($Message, $Title, [System.Windows.Forms.MessageBoxButtons]::OK, $icon) | Out-Null
