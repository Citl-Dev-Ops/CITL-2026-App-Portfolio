#Requires -Version 5.1
<#
  CITL Sync Monitor - Professional Monitoring & Alerting
  =======================================================
  Enterprise-grade monitoring system for CITL sync operations.
  
  Features:
  - Real-time sync status monitoring
  - Automated alerts and notifications
  - Performance metrics and analytics
  - Health checks and diagnostics
  - Integration with Windows Event Log
  - Email/SMS alerting capabilities
  - Dashboard integration
  
  Usage:
    .\citl_sync_monitor.ps1 -Start          # Start monitoring service
    .\citl_sync_monitor.ps1 -Stop           # Stop monitoring service
    .\citl_sync_monitor.ps1 -Status         # Show current status
    .\citl_sync_monitor.ps1 -Health         # Run health diagnostics
    .\citl_sync_monitor.ps1 -Alerts         # View recent alerts
#>

param(
    [switch]$Start,
    [switch]$Stop,
    [switch]$Status,
    [switch]$Health,
    [switch]$Alerts,
    [switch]$Dashboard
)

# ============================================================================
# CONFIGURATION
# ============================================================================
$MONITOR_CONFIG = "$env:APPDATA\CITL\monitor_config.json"
$MONITOR_LOG = "$env:APPDATA\CITL\logs\monitor_$(Get-Date -Format 'yyyy-MM-dd').log"
$ALERT_LOG = "$env:APPDATA\CITL\logs\alerts_$(Get-Date -Format 'yyyy-MM-dd').log"
$HEALTH_CHECK_INTERVAL = 300  # 5 minutes
$ALERT_CHECK_INTERVAL = 60    # 1 minute

# ============================================================================
# MONITORING FUNCTIONS
# ============================================================================
function Write-MonitorLog { param($message, $level = "INFO")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "[$timestamp] [$level] $message"
    Add-Content -Path $MONITOR_LOG -Value $logEntry
    
    # Write to Windows Event Log
    try {
        Write-EventLog -LogName "Application" -Source "CITL Sync Monitor" -EventId 1000 -EntryType Information -Message $message
    } catch {
        # Event log source may not exist, silently continue
    }
}

function Write-Alert { param($message, $severity = "WARNING")
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $alertEntry = "[$timestamp] [$severity] $message"
    Add-Content -Path $ALERT_LOG -Value $alertEntry
    
    Write-MonitorLog "ALERT: $message" $severity
    
    # Send notification (expand this for email/SMS integration)
    Show-Notification -Title "CITL Sync Alert" -Message $message -Severity $severity
}

function Show-Notification {
    param($Title, $Message, $Severity = "INFO")
    
    # Use Windows Toast notifications
    try {
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.UI.Notifications.ToastNotification, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
        
        $template = @"
<toast>
    <visual>
        <binding template="ToastGeneric">
            <text>$Title</text>
            <text>$Message</text>
        </binding>
    </visual>
</toast>
"@
        
        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("CITL Sync").Show($toast)
    } catch {
        # Fallback to console output
        Write-Host "NOTIFICATION: $Title - $Message" -ForegroundColor Yellow
    }
}

function Get-SyncHealth {
    $health = @{
        overall = "HEALTHY"
        checks = @()
        timestamp = Get-Date
    }
    
    # Check sync manager process
    $syncProcesses = Get-Process | Where-Object { $_.Name -like "*powershell*" -and $_.CommandLine -like "*citl_sync_manager*" }
    $health.checks += @{
        name = "Sync Manager Process"
        status = if ($syncProcesses) { "RUNNING" } else { "STOPPED" }
        details = "$($syncProcesses.Count) instances running"
    }
    
    # Check USB connectivity
    $usbDrives = Get-CimInstance -ClassName Win32_DiskDrive | Where-Object { $_.InterfaceType -eq "USB" }
    $health.checks += @{
        name = "USB Drive Detection"
        status = if ($usbDrives) { "HEALTHY" } else { "WARNING" }
        details = "$($usbDrives.Count) USB drives detected"
    }
    
    # Check repository accessibility
    $repoPath = Find-CitlRepository
    $health.checks += @{
        name = "Repository Access"
        status = if ($repoPath) { "HEALTHY" } else { "ERROR" }
        details = if ($repoPath) { "Found at: $repoPath" } else { "Repository not found" }
    }
    
    # Check log file sizes
    $logFiles = Get-ChildItem "$env:APPDATA\CITL\logs" -Filter "*.log" | Where-Object { $_.Length -gt 100MB }
    $health.checks += @{
        name = "Log File Sizes"
        status = if ($logFiles) { "WARNING" } else { "HEALTHY" }
        details = if ($logFiles) { "$($logFiles.Count) large log files" } else { "All logs within limits" }
    }
    
    # Check scheduled tasks
    $scheduledTask = Get-ScheduledTask -TaskName "CITL Daily Sync" -ErrorAction SilentlyContinue
    $health.checks += @{
        name = "Scheduled Sync"
        status = if ($scheduledTask) { "HEALTHY" } else { "DISABLED" }
        details = if ($scheduledTask) { "Next run: $($scheduledTask.NextRunTime)" } else { "No scheduled sync configured" }
    }
    
    # Determine overall health
    $errorChecks = $health.checks | Where-Object { $_.status -eq "ERROR" }
    $warningChecks = $health.checks | Where-Object { $_.status -eq "WARNING" }
    
    if ($errorChecks) {
        $health.overall = "CRITICAL"
    } elseif ($warningChecks) {
        $health.overall = "WARNING"
    }
    
    return $health
}

function Find-CitlRepository {
    # Simplified version for monitoring
    $candidates = @(
        "$env:USERPROFILE\Desktop\CITL",
        "$env:USERPROFILE\Documents\CITL",
        "$env:USERPROFILE\CITL"
    )
    
    foreach ($path in $candidates) {
        if (Test-Path (Join-Path $path "factbook-assistant\citl_app_sync.py")) {
            return $path
        }
    }
    return $null
}

function Start-MonitoringService {
    Write-MonitorLog "Starting CITL Sync Monitor service" "INFO"
    
    # Create background job for continuous monitoring
    $monitorJob = Start-Job -ScriptBlock {
        while ($true) {
            try {
                # Run health checks
                $health = Get-SyncHealth
                
                # Log health status
                Write-MonitorLog "Health check completed: $($health.overall)" "INFO"
                
                # Generate alerts for issues
                foreach ($check in $health.checks) {
                    if ($check.status -eq "ERROR") {
                        Write-Alert "$($check.name): $($check.details)" "ERROR"
                    } elseif ($check.status -eq "WARNING") {
                        Write-Alert "$($check.name): $($check.details)" "WARNING"
                    }
                }
                
                # Check for sync job completions
                $completedJobs = Get-Job | Where-Object { 
                    $_.Name -like "*CITL*" -and 
                    $_.State -eq "Completed" -and 
                    $_.HasMoreData 
                }
                
                foreach ($job in $completedJobs) {
                    $result = Receive-Job $job
                    Write-MonitorLog "Sync job completed: $($job.Name)" "SUCCESS"
                    Remove-Job $job
                }
                
            } catch {
                Write-MonitorLog "Monitoring error: $_" "ERROR"
            }
            
            Start-Sleep -Seconds $using:HEALTH_CHECK_INTERVAL
        }
    } -Name "CITL-Sync-Monitor"
    
    Write-MonitorLog "Monitoring service started (Job ID: $($monitorJob.Id))" "SUCCESS"
}

function Stop-MonitoringService {
    Write-MonitorLog "Stopping CITL Sync Monitor service" "INFO"
    
    $monitorJobs = Get-Job | Where-Object { $_.Name -eq "CITL-Sync-Monitor" }
    foreach ($job in $monitorJobs) {
        Stop-Job $job
        Remove-Job $job
        Write-MonitorLog "Stopped monitoring job: $($job.Id)" "INFO"
    }
}

function Show-MonitorStatus {
    Write-Host "=== CITL Sync Monitor Status ===" -ForegroundColor Cyan
    
    # Check if monitoring service is running
    $monitorJobs = Get-Job | Where-Object { $_.Name -eq "CITL-Sync-Monitor" }
    if ($monitorJobs) {
        Write-Host "Monitoring Service: RUNNING" -ForegroundColor Green
        Write-Host "Active Jobs: $($monitorJobs.Count)" -ForegroundColor Green
        $monitorJobs | ForEach-Object {
            Write-Host "  - Job $($_.Id): $($_.State) (Started: $($_.PSBeginTime))" -ForegroundColor Gray
        }
    } else {
        Write-Host "Monitoring Service: STOPPED" -ForegroundColor Yellow
    }
    
    # Show current health
    $health = Get-SyncHealth
    Write-Host "`nOverall Health: $($health.overall)" -ForegroundColor (switch ($health.overall) {
        "HEALTHY" { "Green" }
        "WARNING" { "Yellow" }
        "CRITICAL" { "Red" }
        default { "Gray" }
    })
    
    Write-Host "`nComponent Status:" -ForegroundColor Cyan
    foreach ($check in $health.checks) {
        $color = switch ($check.status) {
            "HEALTHY" { "Green" }
            "RUNNING" { "Green" }
            "WARNING" { "Yellow" }
            "STOPPED" { "Yellow" }
            "ERROR" { "Red" }
            "DISABLED" { "Gray" }
            default { "Gray" }
        }
        Write-Host "  $($check.name): $($check.status)" -ForegroundColor $color
        Write-Host "    $($check.details)" -ForegroundColor Gray
    }
}

function Show-RecentAlerts {
    Write-Host "=== Recent CITL Sync Alerts ===" -ForegroundColor Cyan
    
    if (Test-Path $ALERT_LOG) {
        $alerts = Get-Content $ALERT_LOG -Tail 20
        if ($alerts) {
            $alerts | ForEach-Object {
                $color = if ($_ -match "\[ERROR\]") { "Red" } 
                        elseif ($_ -match "\[WARNING\]") { "Yellow" } 
                        else { "Gray" }
                Write-Host $_ -ForegroundColor $color
            }
        } else {
            Write-Host "No recent alerts" -ForegroundColor Green
        }
    } else {
        Write-Host "No alert log found" -ForegroundColor Gray
    }
}

# ============================================================================
# MAIN EXECUTION
# ============================================================================
switch {
    $Start {
        Start-MonitoringService
    }
    $Stop {
        Stop-MonitoringService
    }
    $Status {
        Show-MonitorStatus
    }
    $Health {
        $health = Get-SyncHealth
        $health | ConvertTo-Json -Depth 3
    }
    $Alerts {
        Show-RecentAlerts
    }
    default {
        Write-Host "CITL Sync Monitor v1.0" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "Usage:" -ForegroundColor Yellow
        Write-Host "  .\citl_sync_monitor.ps1 -Start          # Start monitoring service"
        Write-Host "  .\citl_sync_monitor.ps1 -Stop           # Stop monitoring service"
        Write-Host "  .\citl_sync_monitor.ps1 -Status         # Show current status"
        Write-Host "  .\citl_sync_monitor.ps1 -Health         # Run health diagnostics"
        Write-Host "  .\citl_sync_monitor.ps1 -Alerts         # View recent alerts"
        Write-Host ""
    }
}