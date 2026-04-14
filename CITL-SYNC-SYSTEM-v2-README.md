# CITL Enterprise Sync System v2.0

## 🚀 Professional IT Sync Solution

The CITL Enterprise Sync System provides automated, professional-grade synchronization for IT operations, featuring enterprise-level automation, monitoring, and deployment capabilities.

## ✨ Key Features

### 🔄 **One-Click Sync**
- **CITL-Sync-OneClick.cmd**: Single-command sync with auto-detection
- Smart USB drive detection and scoring
- Automatic repository discovery
- Background sync operations

### 📊 **Enterprise Monitoring**
- **citl_sync_monitor.ps1**: Real-time monitoring and alerting
- Health checks and diagnostics
- Windows Event Log integration
- Toast notifications for alerts
- Performance metrics and analytics

### ⏰ **Automated Scheduling**
- Daily/weekly sync scheduling via Windows Task Scheduler
- Configurable sync times and frequencies
- Background operation with no user interaction
- Automatic retry on failures

### 🔧 **Professional Build System**
- **Enhanced build_all_citl_exes.ps1**: Parallel builds and testing
- Automated testing and validation
- Build artifact management
- Auto-deployment to sync targets
- Build metrics and reporting

### 📋 **Comprehensive Validation**
- **Enhanced BENCH_TEST_USB_SYNC_INSTALL.ps1**: Enterprise validation
- Multi-target testing (USB + Network + Cloud)
- Cross-platform compatibility checks
- Security and integrity validation

### 🛡️ **Enterprise Security**
- Encrypted sync operations (optional)
- Access control and permissions
- Audit trails and logging
- Secure credential management
- Compliance-ready logging

## 🏗️ Architecture

```
CITL Enterprise Sync System
├── 🎯 Sync Manager (citl_sync_manager.ps1)
│   ├── GUI Dashboard
│   ├── Auto-Detection Engine
│   ├── Background Operations
│   └── Configuration Management
├── 📊 Monitor Service (citl_sync_monitor.ps1)
│   ├── Health Monitoring
│   ├── Alert System
│   ├── Event Logging
│   └── Performance Analytics
├── 🔄 One-Click Launcher (CITL-Sync-OneClick.cmd)
│   ├── Smart Detection
│   ├── Progress Tracking
│   └── Error Recovery
├── 🏭 Build System (build_all_citl_exes.ps1)
│   ├── Parallel Builds
│   ├── Automated Testing
│   ├── Artifact Management
│   └── Auto-Deployment
└── ✅ Validation Suite (BENCH_TEST_USB_SYNC_INSTALL.ps1)
    ├── Multi-Target Testing
    ├── Security Validation
    ├── Performance Benchmarking
    └── Compliance Checking
```

## 🚀 Quick Start

### 1. **One-Click Sync**
```cmd
# From USB drive or repo root
CITL-Sync-OneClick.cmd
```

### 2. **Launch Sync Dashboard**
```powershell
.\scripts\windows\citl_sync_manager.ps1
```

### 3. **Start Monitoring Service**
```powershell
.\scripts\windows\citl_sync_monitor.ps1 -Start
```

### 4. **Setup Automated Sync**
```powershell
.\scripts\windows\citl_sync_manager.ps1 -ScheduleDaily
```

## 📖 Detailed Usage

### Sync Manager Commands

```powershell
# Launch interactive dashboard
.\citl_sync_manager.ps1

# Immediate sync
.\citl_sync_manager.ps1 -SyncNow

# Setup scheduling
.\citl_sync_manager.ps1 -ScheduleDaily
.\citl_sync_manager.ps1 -ScheduleWeekly

# Status and management
.\citl_sync_manager.ps1 -Status
.\citl_sync_manager.ps1 -Rollback
```

### Monitor Service Commands

```powershell
# Service management
.\citl_sync_monitor.ps1 -Start
.\citl_sync_monitor.ps1 -Stop
.\citl_sync_monitor.ps1 -Status

# Diagnostics
.\citl_sync_monitor.ps1 -Health
.\citl_sync_monitor.ps1 -Alerts
```

### Build System Commands

```powershell
# Standard builds
.\build_all_citl_exes.ps1
.\build_all_citl_exes.ps1 -Apps sync,presentation

# Advanced builds
.\build_all_citl_exes.ps1 -Test -Deploy -Parallel
.\build_all_citl_exes.ps1 -Report
```

### Validation Commands

```powershell
# Full validation suite
.\BENCH_TEST_USB_SYNC_INSTALL.ps1

# Quick validation
.\BENCH_TEST_USB_SYNC_INSTALL.ps1 -SkipInstall
```

## 🔧 Configuration

### Sync Configuration (`%APPDATA%\CITL\sync_config.json`)

```json
{
  "version": "2.0.0",
  "last_sync": "2024-01-15T09:00:00Z",
  "sync_targets": [],
  "schedule": {
    "enabled": true,
    "frequency": "daily",
    "time": "09:00"
  },
  "preferences": {
    "auto_detect_usb": true,
    "background_sync": true,
    "notifications": true,
    "compression": true,
    "encryption": false
  },
  "logging": {
    "level": "INFO",
    "max_files": 30,
    "max_size_mb": 100
  }
}
```

### Environment Variables

```cmd
set CITL_REPO=C:\Path\To\CITL\Repository
set CITL_SYNC_LOG_LEVEL=DEBUG
set CITL_SYNC_ENCRYPTION_KEY=your-encryption-key
```

## 📊 Monitoring & Alerts

### Health Checks
- ✅ Sync Manager Process Status
- ✅ USB Drive Connectivity
- ✅ Repository Accessibility
- ✅ Log File Size Management
- ✅ Scheduled Task Status

### Alert Types
- 🚨 **Critical**: Sync failures, repository inaccessibility
- ⚠️ **Warning**: Large log files, USB disconnection
- ℹ️ **Info**: Sync completions, health check results

### Log Locations
- **Sync Logs**: `%APPDATA%\CITL\logs\sync_YYYY-MM-DD.log`
- **Monitor Logs**: `%APPDATA%\CITL\logs\monitor_YYYY-MM-DD.log`
- **Alert Logs**: `%APPDATA%\CITL\logs\alerts_YYYY-MM-DD.log`
- **Build Logs**: `%APPDATA%\CITL\logs\build_YYYY-MM-DD.log`

## 🔒 Security Features

### Encryption
- Optional AES-256 encryption for sync operations
- Secure credential storage
- Encrypted logging options

### Access Control
- Windows user permissions
- Scheduled task security context
- Audit trail logging

### Compliance
- SOC 2 compatible logging
- Data retention policies
- Change management tracking

## 🚀 Deployment Scenarios

### 1. **Corporate IT Environment**
```
Domain Controller → File Server → Workstation Sync
       ↓              ↓              ↓
   Policy Mgmt    Central Repo   Auto-Sync Clients
```

### 2. **Field Operations**
```
USB Drive ←→ Field Laptop ←→ Cloud Sync
   ↓            ↓            ↓
Portable    Offline Work   Backup/Recovery
Install     Environment    Systems
```

### 3. **Development Workflow**
```
Dev Machine → Git Push → CI/CD → Auto Deploy
    ↓            ↓            ↓
Local Test    Code Review   Production Sync
```

## 🛠️ Troubleshooting

### Common Issues

**Sync Manager Won't Start**
```powershell
# Check PowerShell execution policy
Get-ExecutionPolicy
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Verify file permissions
icacls "scripts\windows\citl_sync_manager.ps1"
```

**USB Drive Not Detected**
```powershell
# Check USB drives
Get-CimInstance -ClassName Win32_DiskDrive | Where-Object { $_.InterfaceType -eq "USB" }

# Manual drive detection
.\citl_sync_manager.ps1 -SyncNow -TargetRepo "F:\"
```

**Scheduled Sync Not Running**
```powershell
# Check scheduled tasks
Get-ScheduledTask -TaskName "CITL Daily Sync"

# View task history
Get-ScheduledTaskInfo -TaskName "CITL Daily Sync"
```

### Performance Optimization

**Large Repository Sync**
- Use background sync: `-Background`
- Enable compression in config
- Schedule during off-hours

**Multiple Targets**
- Use parallel sync operations
- Configure target priorities
- Implement bandwidth throttling

## 📈 Metrics & Reporting

### Build Metrics
- Build time tracking
- Success/failure rates
- Artifact size analysis
- Dependency validation

### Sync Metrics
- Transfer speeds
- Success rates
- Error categorization
- Performance trends

### System Health
- CPU/Memory usage
- Disk space monitoring
- Network connectivity
- Service availability

## 🔄 Migration from v1.x

### Automatic Migration
The system automatically detects v1.x configurations and migrates them to v2.0 format.

### Manual Migration Steps
1. Backup existing configuration
2. Run `.\citl_sync_manager.ps1` to initialize v2.0
3. Review and update preferences
4. Test sync operations
5. Enable monitoring service

## 🤝 Integration APIs

### PowerShell Module
```powershell
Import-Module CITLSync

# Programmatic sync
Invoke-CITLSync -Source "C:\Repo" -Target "F:\" -Background

# Health monitoring
Get-CITLHealth | Format-Table
```

### REST API (Future)
```http
POST /api/v1/sync
{
  "source": "C:\\Repo",
  "target": "F:\\",
  "options": {
    "background": true,
    "compression": true
  }
}
```

## 📚 Advanced Configuration

### Custom Sync Profiles
Create profile-specific configurations for different environments:

```json
{
  "profiles": {
    "development": {
      "compression": false,
      "encryption": false,
      "logging": "DEBUG"
    },
    "production": {
      "compression": true,
      "encryption": true,
      "logging": "WARN"
    }
  }
}
```

### Network Proxy Support
Configure proxy settings for cloud sync operations:

```json
{
  "network": {
    "proxy": {
      "http": "http://proxy.company.com:8080",
      "https": "http://proxy.company.com:8080"
    },
    "timeout": 300
  }
}
```

## 🎯 Best Practices

### 1. **Regular Backups**
- Enable automatic configuration backups
- Test restore procedures monthly
- Maintain offsite backup copies

### 2. **Monitoring**
- Enable monitoring service on all sync clients
- Configure alerts for critical operations
- Review logs weekly for anomalies

### 3. **Security**
- Use encryption for sensitive data
- Regularly rotate access credentials
- Audit sync operations quarterly

### 4. **Performance**
- Schedule large syncs during off-hours
- Use compression for bandwidth-limited connections
- Monitor and optimize sync performance

### 5. **Documentation**
- Maintain sync target inventory
- Document custom configurations
- Update procedures for changes

---

## 📞 Support

For enterprise support, training, or custom implementations:

- 📧 Email: citl-support@company.com
- 📱 Phone: 1-800-CITL-SYNC
- 📖 Documentation: https://docs.citl.com/sync
- 🎓 Training: https://training.citl.com

---

*CITL Enterprise Sync System v2.0 - Professional IT Operations Made Simple*