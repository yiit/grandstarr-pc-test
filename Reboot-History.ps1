<#
.SYNOPSIS
    Dokunmatik PC - reset / kapanma / elektrik kesintisi gecmisi raporu.
    Cihazin NE ZAMAN ve NASIL yeniden baslatildigini sinifa ayirir:
      - TEMIZ KAPANMA   : duzgun shutdown (6006)
      - SOFT-RESET      : kullanici/OS baslatti, planli reboot (1074)
      - BEKLENMEDIK     : elektrik kesintisi / hard (manuel) reset / crash (6008, Kernel-Power 41)
      - ACILIS          : sistem acilisi (6005)

.DESCRIPTION
    Windows bu olaylari System olay gunlugune KALICI yazar; ayri bir servise
    gerek yoktur - bu script gunlugu okuyup okunabilir rapor uretir.
    Istege bagli olarak ACILISTA otomatik calisan zamanlanmis gorev kurar
    (-Install): her boot'ta gecmisi guncel HTML olarak diske yazar -> "servis gibi".

.USAGE
    Yonetici PowerShell:
      .\Reboot-History.ps1                 # son 30 gun, ekran + HTML
      .\Reboot-History.ps1 -Days 90        # son 90 gun
      .\Reboot-History.ps1 -Install        # acilista otomatik rapor gorevini kur
      .\Reboot-History.ps1 -Uninstall      # gorevi kaldir

.NOTES
    Cikti: reboot_<PC>_<tarih>.html  ve  reboot_<PC>_<tarih>.csv
    NOT: 6008/41 olaylari "elektrik kesintisi" ile "manuel/hard reset dugmesi"ni
         AYIRT EDEMEZ - ikisi de Windows'a "kirli kapanma" olarak gorunur.
         (Battery/UPS log'u varsa elektrik kesintisi ayrica dogrulanabilir.)
#>

[CmdletBinding()]
param(
    [int]    $Days = 30,
    [switch] $Install,     # acilista otomatik rapor ureten zamanlanmis gorevi kur
    [switch] $Uninstall,   # gorevi kaldir
    [switch] $Quiet        # konsola yazma (gorev modunda)
)

[System.Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture
$ErrorActionPreference = 'Continue'
$TaskName = 'Endutek-RebootHistory'

# .ps1 mi yoksa ps2exe ile derlenmis .exe mi calisiyor?
$ExePath = ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName)
$IsExe   = $ExePath -notmatch 'powershell|pwsh'
$BaseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $ExePath }

# --------------------------------------------------------------------
function Test-Admin {
    $id=[Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ---- ACILISTA OTOMATIK GOREV KUR / KALDIR ("servis gibi") ----------
if ($Install) {
    if (-not (Test-Admin)) { Write-Host "Kurulum icin Yonetici gerekir." -ForegroundColor Red; exit 2 }
    if ($IsExe) {
        # Derlenmis exe: gorev dogrudan exe'yi calistirsin
        $action = New-ScheduledTaskAction -Execute $ExePath -Argument "-Days 365 -Quiet"
    } else {
        $script = $MyInvocation.MyCommand.Path
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' `
                    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`" -Days 365 -Quiet"
    }
    $trigger = New-ScheduledTaskTrigger -AtStartup
    $set     = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable:$false
    $pr      = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $set -Principal $pr -Force -Description 'Her acilista reset/elektrik gecmisi raporu uretir' | Out-Null
    Write-Host "Kuruldu: '$TaskName' (her acilista calisir, rapor: $BaseDir)" -ForegroundColor Green
    exit 0
}
if ($Uninstall) {
    if (-not (Test-Admin)) { Write-Host "Kaldirma icin Yonetici gerekir." -ForegroundColor Red; exit 2 }
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Kaldirildi: '$TaskName'" -ForegroundColor Green
    exit 0
}

# ---- OLAYLARI TOPLA & SINIFLANDIR ----------------------------------
$since = (Get-Date).AddDays(-$Days)
$events = [System.Collections.Generic.List[object]]::new()
try {
    $raw = Get-WinEvent -FilterHashtable @{ LogName='System'; Id=6005,6006,6008,1074,1076,41; StartTime=$since } -ErrorAction Stop
} catch { $raw = @() }

foreach ($e in ($raw | Sort-Object TimeCreated)) {
    $type=''; $detail=''
    switch ($e.Id) {
        6006 { $type='TEMIZ KAPANMA';  $detail='Duzgun kapatildi.' }
        6005 { $type='ACILIS';         $detail='Sistem acildi.' }
        6008 { $type='BEKLENMEDIK';    $detail='Onceki kapanma kirliydi: ELEKTRIK KESINTISI veya MANUEL/HARD RESET.' }
        41   { $type='BEKLENMEDIK';    $detail='Kernel-Power 41: duzgun kapanmadan yeniden basladi (elektrik/hard-reset/crash).' }
        1074 { $type='SOFT-RESET';     $detail=(($e.Message -split "`r?`n") | Where-Object {$_} | Select-Object -First 1) }
        1076 { $type='BEKLENMEDIK';    $detail=(($e.Message -split "`r?`n") | Where-Object {$_} | Select-Object -First 1) }
    }
    $events.Add([pscustomobject]@{
        Time   = $e.TimeCreated
        Id     = $e.Id
        Type   = $type
        Detail = ($detail -replace '\s+',' ').Trim()
    })
}

# ---- SAYIMLAR ------------------------------------------------------
$cClean  = @($events | Where-Object Type -eq 'TEMIZ KAPANMA').Count
$cSoft   = @($events | Where-Object Type -eq 'SOFT-RESET').Count
$cUnexp  = @($events | Where-Object Type -eq 'BEKLENMEDIK').Count
$cBoot   = @($events | Where-Object Type -eq 'ACILIS').Count

if (-not $Quiet) {
    try { Clear-Host } catch {}
    Write-Host "================================================================" -ForegroundColor White
    Write-Host "   RESET / KAPANMA / ELEKTRIK GECMISI  -  son $Days gun" -ForegroundColor White
    Write-Host "   $env:COMPUTERNAME   |   $($since.ToString('yyyy-MM-dd')) sonrasi" -ForegroundColor White
    Write-Host "================================================================" -ForegroundColor White
    Write-Host ("Acilis: {0}   Temiz kapanma: {1}   Soft-reset: {2}   BEKLENMEDIK: {3}`n" -f $cBoot,$cClean,$cSoft,$cUnexp) `
        -ForegroundColor $(if($cUnexp -gt 0){'Yellow'}else{'Green'})
    foreach ($x in $events) {
        $col = switch ($x.Type) { 'BEKLENMEDIK'{'Red'} 'SOFT-RESET'{'Yellow'} 'TEMIZ KAPANMA'{'Green'} default{'Gray'} }
        Write-Host ("{0}  [{1,-14}]  {2}" -f $x.Time.ToString('yyyy-MM-dd HH:mm:ss'), $x.Type, $x.Detail) -ForegroundColor $col
    }
}

# ---- DOSYALAR ------------------------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$base  = Join-Path $BaseDir ("reboot_{0}_{1}" -f $env:COMPUTERNAME,$stamp)
$events | Select-Object @{n='Zaman';e={$_.Time.ToString('yyyy-MM-dd HH:mm:ss')}},Id,Type,Detail |
    Export-Csv -Path "$base.csv" -NoTypeInformation -Encoding UTF8

$rows = ($events | ForEach-Object {
    $cls = switch ($_.Type) { 'BEKLENMEDIK'{'fail'} 'SOFT-RESET'{'warn'} 'TEMIZ KAPANMA'{'pass'} default{'' } }
    "<tr class='$cls'><td>$($_.Time.ToString('yyyy-MM-dd HH:mm:ss'))</td><td>$($_.Id)</td><td>$($_.Type)</td><td>$($_.Detail)</td></tr>"
}) -join "`n"

@"
<!doctype html><html><head><meta charset='utf-8'><title>Reset Gecmisi - $env:COMPUTERNAME</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,Arial;margin:24px}
h1{font-size:22px}.mut{color:#8b949e}
.cards{display:flex;gap:14px;margin:14px 0}.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px 20px;min-width:130px}
.card b{font-size:26px;display:block}.red{color:#f85149}.green{color:#3fb950}.yellow{color:#d29922}
table{border-collapse:collapse;width:100%;margin-top:14px}td,th{border:1px solid #30363d;padding:6px 12px;text-align:left}
th{background:#161b22}.fail{background:#3d1414}.warn{background:#3d3414}.pass{background:#0f2d1a}</style></head><body>
<h1>Reset / Kapanma / Elektrik Gecmisi</h1>
<p class='mut'>$env:COMPUTERNAME &nbsp;|&nbsp; son $Days gun &nbsp;|&nbsp; rapor: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')</p>
<div class='cards'>
<div class='card'>Acilis<b>$cBoot</b></div>
<div class='card'>Temiz kapanma<b class='green'>$cClean</b></div>
<div class='card'>Soft-reset<b class='yellow'>$cSoft</b></div>
<div class='card'>Beklenmedik<b class='red'>$cUnexp</b></div>
</div>
<p class='mut'>Not: "Beklenmedik" = elektrik kesintisi VEYA manuel/hard-reset; Windows ikisini ayirt edemez.</p>
<table><tr><th>Zaman</th><th>Olay ID</th><th>Tip</th><th>Aciklama</th></tr>
$rows
</table></body></html>
"@ | Set-Content -Path "$base.html" -Encoding UTF8

if (-not $Quiet) {
    Write-Host "`nCSV : $base.csv"  -ForegroundColor Cyan
    Write-Host "HTML: $base.html"   -ForegroundColor Cyan
    try { Start-Process "$base.html" } catch {}
}
exit 0
