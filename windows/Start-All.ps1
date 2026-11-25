param([string]$NapCatHome = '')

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$envFile = Join-Path $root '.env'
$localConfig = @()
if (Test-Path -LiteralPath $envFile) {
    $localConfig = Get-Content -LiteralPath $envFile -Encoding UTF8
}

function Get-LocalSetting([string]$Name) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { return $value }
    $pattern = '^\s*' + [regex]::Escape($Name) + '\s*='
    $line = $localConfig | Where-Object { $_ -match $pattern } | Select-Object -Last 1
    if ($line) { return ($line -split '=', 2)[1].Trim().Trim('"', "'") }
    return ''
}

function Get-LocalPort([string]$Name, [int]$Default) {
    $value = Get-LocalSetting $Name
    if (-not $value) { return $Default }
    $port = 0
    if (-not [int]::TryParse($value, [ref]$port) -or $port -lt 1 -or $port -gt 65535) {
        throw "Invalid port in $Name."
    }
    return $port
}

function Test-LocalPort([int]$Port) {
    $client = New-Object Net.Sockets.TcpClient
    try {
        $task = $client.ConnectAsync('127.0.0.1', $Port)
        if (-not $task.Wait(350)) { return $false }
        return $client.Connected
    } catch { return $false }
    finally { $client.Dispose() }
}

function Get-AssistantResponse([string]$Url) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -MaximumRedirection 0
        if ($response.Headers['X-SchoolQQ'] -eq 'assistant') { return $response }
    } catch {}
    return $null
}

function Test-NapCatWebUI([string]$Url) {
    try {
        $page = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 2 -MaximumRedirection 0
        return $page.StatusCode -eq 200 -and
            ([string]$page.Headers['Content-Type']) -match '^text/html(?:;|$)' -and
            $page.Content -match '(?is)<title\b[^>]*>[^<]*\bNapCat(?:QQ)?\b[^<]*</title>'
    } catch { return $false }
}

function Find-NapCat {
    $candidates = @($NapCatHome, (Get-LocalSetting 'NAPCAT_HOME'),
        (Join-Path $root 'napcat\napcat'),
        (Join-Path $root 'napcat'),
        (Join-Path $root '..\napcat\napcat'),
        (Join-Path $root '..\napcat'))
    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Container) -and
            (Test-Path -LiteralPath (Join-Path $candidate 'napcat.mjs') -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }
    return ''
}

function Get-NapCatPort([string]$Directory) {
    $defaultPort = 6099
    if ($Directory) {
        $config = Join-Path $Directory 'config\webui.json'
        if (Test-Path -LiteralPath $config -PathType Leaf) {
            try {
                $webui = Get-Content -LiteralPath $config -Raw -Encoding UTF8 | ConvertFrom-Json
                $port = 0
                if ([int]::TryParse([string]$webui.port, [ref]$port) -and $port -ge 0 -and $port -le 65535) {
                    $defaultPort = $port
                }
            } catch {}
        }
    }
    return (Get-LocalPort 'NAPCAT_WEBUI_PORT' $defaultPort)
}

function Install-Page([string]$Directory, [string]$AssistantUrl) {
    $source = Join-Path $root 'napcat-plugin-schoolqq'
    $target = Join-Path $Directory 'plugins\napcat-plugin-schoolqq'
    $webui = Join-Path $target 'webui'
    New-Item -ItemType Directory -Force -Path $webui | Out-Null
    $changed = $false
    foreach ($name in @('index.mjs', 'package.json', 'webui\index.html')) {
        $from = Join-Path $source $name
        $to = Join-Path $target $name
        $content = [IO.File]::ReadAllText($from)
        if ($name -eq 'webui\index.html') {
            $content = $content.Replace('http://127.0.0.1:8080/assistant/', $assistantUrl)
        }
        if (-not (Test-Path -LiteralPath $to) -or [IO.File]::ReadAllText($to) -cne $content) {
            [IO.File]::WriteAllText($to, $content)
            $changed = $true
        }
    }
    return $changed
}

function Start-SchoolQQ {
    $assistantPort = Get-LocalPort 'PORT' 8080
    $napcat = Find-NapCat
    $napcatPort = Get-NapCatPort $napcat
    if ($assistantPort -eq $napcatPort) { throw 'The assistant and NapCat WebUI need different ports.' }

    $assistantUrl = "http://127.0.0.1:${assistantPort}/assistant/"
    $napcatUrl = "http://127.0.0.1:${napcatPort}/webui/"
    $assistant = Get-AssistantResponse $assistantUrl
    if (-not $assistant -and (Test-LocalPort $assistantPort)) {
        throw "Port $assistantPort is already in use. If an older schoolqq is running, stop it and rerun Start-All.cmd."
    }

    $napcatReady = $napcatPort -gt 0 -and (Test-NapCatWebUI $napcatUrl)
    $pluginReady = $false
    $launcher = $null
    if ($napcat -and $napcatPort -gt 0) {
        try {
            $pluginChanged = Install-Page $napcat $assistantUrl
            $pluginReady = $true
            if ($pluginChanged -and $napcatReady) {
                Write-Host 'Plugin updated. Restart NapCat once if the sidebar page is missing or stale.'
            }
        } catch {
            Write-Warning 'Could not install the sidebar plugin. The standalone assistant is still available.'
        }
        if (-not $napcatReady) {
            if (Test-LocalPort $napcatPort) {
                Write-Warning "Port $napcatPort is in use, but it did not return a NapCat WebUI. Check the actual WebUI port."
            } else {
                $windows10 = [Environment]::OSVersion.Version.Build -lt 22000
                $launchers = if ($windows10) {
                    @('launcher-win10-user.bat', 'launcher-win10.bat', 'launcher-user.bat', 'launcher.bat')
                } else {
                    @('launcher-user.bat', 'launcher.bat', 'launcher-win10-user.bat', 'launcher-win10.bat')
                }
                $launcher = $launchers | ForEach-Object { Join-Path $napcat $_ } |
                    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } | Select-Object -First 1
                if ($launcher) {
                    Start-Process -FilePath $launcher -WorkingDirectory $napcat -WindowStyle Minimized
                    Write-Host 'Starting NapCat...'
                } else {
                    Write-Warning 'NapCat launcher not found. Check NAPCAT_HOME in .env.'
                }
            }
        }
    }

    $wait = [Diagnostics.Stopwatch]::StartNew()
    if (-not $assistant) {
        if ($napcatReady -or ($pluginReady -and $launcher)) {
            $env:NAPCAT_WEBUI_PORT = [string]$napcatPort
        }
        Start-Process -FilePath (Join-Path $PSScriptRoot 'Start-Native.cmd') -WorkingDirectory $root -WindowStyle Minimized
        Write-Host 'Starting schoolqq assistant...'
        do {
            Start-Sleep -Seconds 1
            $assistant = Get-AssistantResponse $assistantUrl
        } until ($assistant -or $wait.Elapsed.TotalSeconds -ge 120)
        if (-not $assistant) {
            throw 'Assistant is not ready. Open its minimized console to see the startup status.'
        }
    }

    if ($launcher) {
        do {
            $napcatReady = Test-NapCatWebUI $napcatUrl
            if (-not $napcatReady -and $wait.Elapsed.TotalSeconds -lt 45) { Start-Sleep -Seconds 1 }
        } until ($napcatReady -or $wait.Elapsed.TotalSeconds -ge 45)
    }

    $policy = [string]$assistant.Headers['Content-Security-Policy']
    $canFrame = $policy.Contains("frame-ancestors http://127.0.0.1:${napcatPort};")
    if ($napcatReady -and $canFrame -and ($pluginReady -or -not $napcat)) {
        Start-Process $napcatUrl
        Write-Host 'Opened NapCat WebUI. Open the schoolqq sidebar page.'
    } else {
        Start-Process $assistantUrl
        if ($napcatReady -and -not $canFrame) {
            Write-Host 'Opened the assistant. Stop the existing assistant and run Start-All.cmd to enable the sidebar.'
        } else {
            Write-Host 'Opened the assistant. Check NapCat and NAPCAT_HOME for the sidebar integration.'
        }
    }
}

$mutex = [System.Threading.Mutex]::new($false, 'Local\SchoolQQ.StartAll')
$ownsLock = $false
try {
    try { $ownsLock = $mutex.WaitOne(0) }
    catch [System.Threading.AbandonedMutexException] { $ownsLock = $true }
    if ($ownsLock) { Start-SchoolQQ }
    else { Write-Host 'SchoolQQ is already starting.' }
} finally {
    if ($ownsLock) { $mutex.ReleaseMutex() }
    $mutex.Dispose()
}
