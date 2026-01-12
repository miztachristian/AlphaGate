param(
    [string]$ServerIP = "146.190.235.5",
    [string]$User = "root"
)

$RemotePath = "/opt/trade-app"
$ArchiveName = "trade-app-deploy.tar.gz"

Write-Host "Deploying to $User@$ServerIP..." -ForegroundColor Cyan

# 1. Create Archive (excluding venv, cache, etc)
Write-Host "Creating archive..."
tar -czf $ArchiveName --exclude=.venv --exclude=__pycache__ --exclude=.git --exclude=.pytest_cache --exclude=reports --exclude=*.db src data deployment scripts config.yaml requirements.txt main.py run_live_stocks.py README.md .env

if (-not (Test-Path $ArchiveName)) {
    Write-Error "Failed to create archive!"
    exit 1
}

# 2. Copy Archive
Write-Host "Uploading archive to server..."
scp $ArchiveName "${User}@${ServerIP}:/tmp/${ArchiveName}"

if ($LASTEXITCODE -ne 0) {
    Write-Error "SCP failed. Please check your SSH connection/key."
    Remove-Item $ArchiveName
    exit 1
}

# 3. Remote Setup
Write-Host "Running remote setup..."
# We combine commands into a single line to avoid Windows newline issues (\r\n) over SSH
$RemoteCommands = "mkdir -p $RemotePath && " +
                  "tar -xzf /tmp/$ArchiveName -C $RemotePath && " +
                  "cd $RemotePath && " +
                  "sed -i 's/\r$//' deployment/setup_server.sh && " +
                  "chmod +x deployment/setup_server.sh && " +
                  "./deployment/setup_server.sh && " +
                  "rm /tmp/$ArchiveName"

ssh "${User}@${ServerIP}" "$RemoteCommands"

# 4. Cleanup
Remove-Item $ArchiveName
Write-Host "Deployment Complete!" -ForegroundColor Green
Write-Host "Next steps:"
Write-Host "1. SSH into server: ssh $User@$ServerIP"
Write-Host "2. Edit .env file: nano $RemotePath/.env"
Write-Host "3. Run the app or enable the service."
