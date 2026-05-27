<#
.SYNOPSIS
    Dokunmatik PC uretim hatti donanim test araci.
    CPU / RAM / SSD / Ag / GPU / BIOS envanteri + stress + saglik testleri.

.DESCRIPTION
    Kurulum gerektirmez. Yonetici (Administrator) olarak calistirin.
    J1900, i5 3.nesil gibi dusuk guclu/eski anakartlarda da calisir;
    okunamayan degerler (orn. CPU sicakligi) zarifce "N/A" gecer.

.USAGE
    1) PowerShell'i Yonetici olarak ac
    2) Set-ExecutionPolicy -Scope Process Bypass -Force
    3) .\Test-Hardware.ps1
       .\Test-Hardware.ps1 -StressSeconds 30 -Html

.NOTES
    Rapor: ayni klasore <BilgisayarAdi>_<tarih>.txt (ve -Html ile .html) yazilir.
#>

[CmdletBinding()]
param(
    [int]    $StressSeconds = 20,      # CPU/RAM stress test suresi (saniye)
    [int]    $SsdTestSizeMB = 512,     # SSD hiz testi dosya boyutu (MB)
    [string] $PingHost      = "8.8.8.8",
    [switch] $Html,                    # Ek olarak HTML rapor uret
    [switch] $SkipStress               # Stress testlerini atla (hizli envanter)
)

# =====================================================================
#  BEKLENEN DEGERLER  --  uretim hattinda burayi kendine gore ayarla
# =====================================================================
$Expected = @{
    MinRamGB        = 4       # En az bu kadar RAM olmali
    MinDiskGB       = 100     # Sistem diski en az bu kadar olmali
    MinSsdWriteMBs  = 80      # SSD min yazma hizi (HDD ise dusur)
    MinSsdReadMBs   = 150     # SSD min okuma hizi
    MaxCpuTempC     = 90      # Stress sonu max CPU sicakligi (okunabilirse)
    RequireEthernet = $true   # Ethernet portu zorunlu mu
    RequireWifi     = $false  # WiFi zorunlu mu
}

# ----------------------------------------------------------------------
$ErrorActionPreference = 'Continue'

# Rapor klasoru: .ps1 calisirken script klasoru, .exe (ps2exe) ise exe klasoru
$BaseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) }

$results = [System.Collections.Generic.List[object]]::new()
$report  = [System.Collections.Generic.List[string]]::new()

function Add-Result {
    param([string]$Category,[string]$Item,[string]$Value,[ValidateSet('PASS','FAIL','WARN','INFO')][string]$Status='INFO')
    $results.Add([pscustomobject]@{ Category=$Category; Item=$Item; Value=$Value; Status=$Status })
}

function Write-Line { param([string]$Text,[string]$Color='Gray'); Write-Host $Text -ForegroundColor $Color; $report.Add($Text) }
function Write-Head { param([string]$Text); Write-Host ""; Write-Host "==== $Text ====" -ForegroundColor Cyan; $report.Add(""); $report.Add("==== $Text ====") }

function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

# ======================================================================
try { Clear-Host } catch {}
Write-Host "================================================================" -ForegroundColor White
Write-Host "      DOKUNMATIK PC  --  DONANIM TEST ARACI" -ForegroundColor White
Write-Host "      $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')   |   $env:COMPUTERNAME" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor White

if (-not (Test-Admin)) {
    Write-Host "`n[!] UYARI: Yonetici degil. SMART/sicaklik gibi bazi testler eksik kalabilir.`n" -ForegroundColor Yellow
}

# ======================================================================
#  1) SISTEM / ANAKART / BIOS
# ======================================================================
Write-Head "SISTEM / ANAKART / BIOS"
try {
    $cs   = Get-CimInstance Win32_ComputerSystem
    $bios = Get-CimInstance Win32_BIOS
    $bb   = Get-CimInstance Win32_BaseBoard
    $os   = Get-CimInstance Win32_OperatingSystem

    Write-Line ("Uretici/Model : {0} {1}" -f $cs.Manufacturer, $cs.Model)
    Write-Line ("Anakart       : {0} {1}" -f $bb.Manufacturer, $bb.Product)
    Write-Line ("BIOS          : {0}  v{1}  ({2})" -f $bios.Manufacturer, $bios.SMBIOSBIOSVersion, $bios.ReleaseDate)
    Write-Line ("Seri No       : {0}" -f $bios.SerialNumber)
    Write-Line ("Isletim Sis.  : {0} {1} (build {2})" -f $os.Caption, $os.OSArchitecture, $os.BuildNumber)
    Add-Result 'Sistem' 'Anakart' ("{0} {1}" -f $bb.Manufacturer,$bb.Product) 'INFO'
    Add-Result 'Sistem' 'Seri No' $bios.SerialNumber 'INFO'
} catch { Write-Line "Sistem bilgisi okunamadi: $_" 'Red' }

# ======================================================================
#  2) CPU
# ======================================================================
Write-Head "ISLEMCI (CPU)"
try {
    $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
    Write-Line ("Model         : {0}" -f $cpu.Name.Trim())
    Write-Line ("Cekirdek/Mantiksal : {0} / {1}" -f $cpu.NumberOfCores, $cpu.NumberOfLogicalProcessors)
    Write-Line ("Hiz           : {0} MHz (max {1} MHz)" -f $cpu.CurrentClockSpeed, $cpu.MaxClockSpeed)
    Add-Result 'CPU' 'Model' $cpu.Name.Trim() 'INFO'
    Add-Result 'CPU' 'Cekirdek' ("{0}c/{1}t" -f $cpu.NumberOfCores,$cpu.NumberOfLogicalProcessors) 'INFO'
} catch { Write-Line "CPU bilgisi okunamadi: $_" 'Red' }

function Get-CpuTempC {
    # Cogu masaustu/J1900'de WMI sicaklik DESTEKLENMEZ -> $null doner
    try {
        $t = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop |
             Select-Object -First 1
        if ($t) { return [math]::Round(($t.CurrentTemperature / 10) - 273.15, 1) }
    } catch {}
    return $null
}

# ======================================================================
#  3) RAM
# ======================================================================
Write-Head "BELLEK (RAM)"
$totalRamGB = 0
try {
    $banks = Get-CimInstance Win32_PhysicalMemory
    foreach ($b in $banks) {
        $gb = [math]::Round($b.Capacity/1GB,0)
        $totalRamGB += $gb
        Write-Line ("Slot {0,-12}: {1} GB  {2} MHz  {3}" -f $b.DeviceLocator, $gb, $b.Speed, $b.Manufacturer)
    }
    Write-Line ("TOPLAM RAM    : {0} GB" -f $totalRamGB)
    if ($totalRamGB -ge $Expected.MinRamGB) {
        Add-Result 'RAM' 'Toplam' ("$totalRamGB GB") 'PASS'
    } else {
        Add-Result 'RAM' 'Toplam' ("$totalRamGB GB (beklenen >= $($Expected.MinRamGB) GB)") 'FAIL'
        Write-Line ("  [FAIL] RAM beklenenden az!") 'Red'
    }
} catch { Write-Line "RAM bilgisi okunamadi: $_" 'Red' }

# ======================================================================
#  4) DISK / SSD  (envanter + SMART saglik)
# ======================================================================
Write-Head "DISK / SSD"
try {
    $pds = Get-PhysicalDisk -ErrorAction Stop
    foreach ($pd in $pds) {
        $sizeGB = [math]::Round($pd.Size/1GB,0)
        Write-Line ("Disk          : {0}  {1} GB  ({2}, Bus {3})" -f $pd.FriendlyName, $sizeGB, $pd.MediaType, $pd.BusType)
        $health = $pd.HealthStatus
        $st = if ($health -eq 'Healthy') {'PASS'} else {'FAIL'}
        Write-Line ("  Saglik      : {0}" -f $health) ($(if($st -eq 'PASS'){'Green'}else{'Red'}))
        Add-Result 'Disk' $pd.FriendlyName ("$sizeGB GB / $health") $st

        # SMART guvenilirlik sayaclari (yonetici gerekir)
        try {
            $rc = $pd | Get-StorageReliabilityCounter -ErrorAction Stop
            if ($rc.Temperature)        { Write-Line ("  Sicaklik    : {0} C" -f $rc.Temperature) }
            if ($rc.Wear -ne $null)     { Write-Line ("  Asinma(Wear): %{0}" -f $rc.Wear) }
            if ($rc.ReadErrorsTotal)    { Write-Line ("  Okuma Hata  : {0}" -f $rc.ReadErrorsTotal) }
            if ($rc.WriteErrorsTotal)   { Write-Line ("  Yazma Hata  : {0}" -f $rc.WriteErrorsTotal) }
            if ($rc.PowerOnHours)       { Write-Line ("  Calisma Saat: {0} saat" -f $rc.PowerOnHours) }
        } catch {}
    }
} catch {
    Write-Line "Get-PhysicalDisk basarisiz, Win32_DiskDrive'a dusuluyor..." 'Yellow'
    Get-CimInstance Win32_DiskDrive | ForEach-Object {
        Write-Line ("Disk          : {0}  {1} GB" -f $_.Model, [math]::Round($_.Size/1GB,0))
    }
}

# ----- Sistem diski bos alan
try {
    $sys = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
    $freeGB  = [math]::Round($sys.FreeSpace/1GB,1)
    $totalGB = [math]::Round($sys.Size/1GB,1)
    Write-Line ("Sistem Diski  : {0}  {1} GB / {2} GB bos" -f $env:SystemDrive, $freeGB, $totalGB)
    $st = if ($totalGB -ge $Expected.MinDiskGB) {'PASS'} else {'WARN'}
    Add-Result 'Disk' 'Sistem Boyutu' ("$totalGB GB") $st
} catch {}

# ======================================================================
#  5) GPU / EKRAN KARTI
# ======================================================================
Write-Head "EKRAN KARTI / COZUNURLUK"
try {
    Get-CimInstance Win32_VideoController | ForEach-Object {
        Write-Line ("GPU           : {0}" -f $_.Name)
        if ($_.CurrentHorizontalResolution) {
            Write-Line ("  Cozunurluk  : {0} x {1} @ {2} Hz" -f $_.CurrentHorizontalResolution, $_.CurrentVerticalResolution, $_.CurrentRefreshRate)
        }
        Add-Result 'GPU' 'Adaptor' $_.Name 'INFO'
    }
} catch { Write-Line "GPU bilgisi okunamadi: $_" 'Red' }

# ======================================================================
#  6) AG (Ethernet + WiFi)
# ======================================================================
Write-Head "AG (ETHERNET / WIFI)"
$hasEth = $false; $hasWifi = $false
try {
    $adapters = Get-NetAdapter -ErrorAction Stop | Where-Object { $_.Virtual -eq $false -or $_.HardwareInterface }
    foreach ($a in $adapters) {
        $up = $a.Status -eq 'Up'
        # LinkSpeed string ("1 Gbps") gelir; sayisal hiz icin ReceiveLinkSpeed (bit/sn) kullan
        $mbps = if ($a.ReceiveLinkSpeed) { [math]::Round($a.ReceiveLinkSpeed/1e6,0) } else { 0 }
        $line = "{0,-28} : {1}  ({2} Mbps)  MAC {3}" -f $a.InterfaceDescription, $a.Status, $mbps, $a.MacAddress
        Write-Line $line ($(if($up){'Green'}else{'Gray'}))
        if ($a.MediaType -match '802.3' -or $a.Name -match 'Ethernet') { $hasEth = $true }
        if ($a.Name -match 'Wi-?Fi|Wireless' -or $a.PhysicalMediaType -match 'Native 802.11') { $hasWifi = $true }
    }
} catch { Write-Line "Ag adaptoru okunamadi: $_" 'Red' }

# Ethernet zorunluluk kontrol
if ($Expected.RequireEthernet) {
    $linkUp = (Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object { $_.Name -match 'Ethernet' -and $_.Status -eq 'Up' })
    if ($linkUp) { Add-Result 'Ag' 'Ethernet link' 'Up' 'PASS' }
    else { Add-Result 'Ag' 'Ethernet link' 'Down/Yok' 'WARN'; Write-Line "  [WARN] Ethernet kablosu takili degil ya da port yok." 'Yellow' }
}

# WiFi sinyal (varsa)
try {
    $wlan = netsh wlan show interfaces 2>$null
    if ($wlan -match 'SSID') {
        $ssid = ($wlan | Select-String 'SSID\s+:').ToString().Split(':')[1].Trim()
        $sig  = ($wlan | Select-String 'Signal').ToString().Split(':')[1].Trim()
        Write-Line ("WiFi          : '{0}'  sinyal {1}" -f $ssid, $sig) 'Green'
        Add-Result 'Ag' 'WiFi' ("$ssid / $sig") 'PASS'
    } elseif ($hasWifi) {
        Write-Line "WiFi          : adaptor var, bagli degil" 'Yellow'
    }
} catch {}

# Internet ping testi
Write-Line ""
Write-Line ("Ping testi -> {0} ..." -f $PingHost)
try {
    $ping = Test-Connection -ComputerName $PingHost -Count 4 -ErrorAction Stop
    $avg = [math]::Round(($ping | Measure-Object -Property ResponseTime -Average).Average,0)
    Write-Line ("  Internet OK   : ort. {0} ms" -f $avg) 'Green'
    Add-Result 'Ag' 'Internet' ("$avg ms") 'PASS'
} catch {
    Write-Line "  Internet YOK / ping basarisiz" 'Red'
    Add-Result 'Ag' 'Internet' 'Yok' 'WARN'
}

# ======================================================================
#  7) CPU + RAM STRESS TEST
# ======================================================================
if (-not $SkipStress) {
    Write-Head ("STRESS TEST  ({0} sn)" -f $StressSeconds)
    $tempBefore = Get-CpuTempC
    if ($tempBefore) { Write-Line ("CPU sicaklik (once) : {0} C" -f $tempBefore) }

    # --- CPU: tum mantiksal cekirdeklere yuk bin
    $cores = [Environment]::ProcessorCount
    Write-Line ("CPU yukleniyor: {0} is parcacigi, {1} sn..." -f $cores, $StressSeconds)
    $jobs = 1..$cores | ForEach-Object {
        Start-Job -ScriptBlock {
            param($sec)
            $end = (Get-Date).AddSeconds($sec)
            $x = 0.0001
            while ((Get-Date) -lt $end) { $x = [math]::Sqrt($x*3.14159) + [math]::Sin($x); $x += 0.0001 }
        } -ArgumentList $StressSeconds
    }
    $sw = [Diagnostics.Stopwatch]::StartNew()
    while ($jobs.State -contains 'Running') {
        Start-Sleep -Milliseconds 500
        $pct = [math]::Min(100, [math]::Round(($sw.Elapsed.TotalSeconds/$StressSeconds)*100))
        Write-Progress -Activity "CPU Stress" -Status "$pct%" -PercentComplete $pct
    }
    Write-Progress -Activity "CPU Stress" -Completed
    $jobs | Receive-Job | Out-Null
    $jobs | Remove-Job -Force
    Write-Line ("  CPU stress tamamlandi ({0:n1} sn)" -f $sw.Elapsed.TotalSeconds) 'Green'

    $tempAfter = Get-CpuTempC
    if ($tempAfter) {
        $col = if ($tempAfter -le $Expected.MaxCpuTempC) {'Green'} else {'Red'}
        Write-Line ("CPU sicaklik (sonra): {0} C" -f $tempAfter) $col
        $st = if ($tempAfter -le $Expected.MaxCpuTempC) {'PASS'} else {'FAIL'}
        Add-Result 'Stress' 'CPU max sicaklik' ("$tempAfter C") $st
    } else {
        Write-Line "CPU sicaklik: bu anakartta WMI'dan okunamiyor (J1900/eski board normal)." 'Yellow'
        Add-Result 'Stress' 'CPU sicaklik' 'N/A (okunamadi)' 'INFO'
    }
    Add-Result 'Stress' 'CPU yuk testi' 'Tamamlandi' 'PASS'

    # --- RAM: yaz/oku dogrulama (mevcut bos RAM'in bir kismi)
    Write-Line ""
    Write-Line "RAM yaz/oku dogrulama testi..."
    try {
        $os = Get-CimInstance Win32_OperatingSystem
        $freeMB = [math]::Round($os.FreePhysicalMemory/1024,0)
        $testMB = [math]::Min(512, [math]::Floor($freeMB*0.3))   # guvenli: bos RAM'in %30'u, max 512MB
        if ($testMB -lt 16) { $testMB = 16 }
        Write-Line ("  {0} MB ayrilip 0xAA / 0x55 pattern yazilip okunuyor..." -f $testMB)
        $count = $testMB * 1MB / 8
        $arr = [long[]]::new($count)
        $pattern = [long]0xAAAAAAAAAAAAAAAA
        for ($i=0; $i -lt $count; $i++) { $arr[$i] = $pattern }
        $ok = $true
        for ($i=0; $i -lt $count; $i++) { if ($arr[$i] -ne $pattern) { $ok=$false; break } }
        $pattern2 = [long]0x5555555555555555
        for ($i=0; $i -lt $count; $i++) { $arr[$i] = $pattern2 }
        for ($i=0; $i -lt $count; $i++) { if ($arr[$i] -ne $pattern2) { $ok=$false; break } }
        $arr = $null; [GC]::Collect()
        if ($ok) { Write-Line ("  [PASS] RAM dogrulama OK ({0} MB)" -f $testMB) 'Green'; Add-Result 'Stress' 'RAM dogrulama' ("$testMB MB OK") 'PASS' }
        else     { Write-Line "  [FAIL] RAM pattern uyusmadi!" 'Red'; Add-Result 'Stress' 'RAM dogrulama' 'HATA' 'FAIL' }
    } catch { Write-Line "  RAM testi hatasi: $_" 'Red' }
}

# ======================================================================
#  8) SSD HIZ TESTI (sequential yaz/oku)
# ======================================================================
if (-not $SkipStress) {
    Write-Head ("SSD HIZ TESTI  ({0} MB)" -f $SsdTestSizeMB)
    $tmp = Join-Path $env:TEMP ("pctest_{0}.bin" -f ([guid]::NewGuid().ToString('N')))
    try {
        $bufMB = 8
        $buffer = [byte[]]::new($bufMB*1MB)
        (New-Object Random).NextBytes($buffer)
        $loops = [int]($SsdTestSizeMB / $bufMB)

        # --- YAZMA
        $sw = [Diagnostics.Stopwatch]::StartNew()
        $fs = [IO.File]::Create($tmp)
        for ($i=0; $i -lt $loops; $i++) { $fs.Write($buffer,0,$buffer.Length) }
        $fs.Flush($true); $fs.Close()
        $sw.Stop()
        $writeMBs = [math]::Round(($bufMB*$loops)/$sw.Elapsed.TotalSeconds,1)
        $st = if ($writeMBs -ge $Expected.MinSsdWriteMBs) {'PASS'} else {'WARN'}
        Write-Line ("Yazma hizi    : {0} MB/s" -f $writeMBs) ($(if($st -eq 'PASS'){'Green'}else{'Yellow'}))
        Add-Result 'SSD' 'Yazma hizi' ("$writeMBs MB/s") $st

        # --- OKUMA (cache'i atlamak icin yeni acilis)
        $sw.Restart()
        $fs = [IO.File]::OpenRead($tmp)
        $rbuf = [byte[]]::new($bufMB*1MB)
        while ($fs.Read($rbuf,0,$rbuf.Length) -gt 0) {}
        $fs.Close()
        $sw.Stop()
        $readMBs = [math]::Round(($bufMB*$loops)/$sw.Elapsed.TotalSeconds,1)
        $st = if ($readMBs -ge $Expected.MinSsdReadMBs) {'PASS'} else {'WARN'}
        Write-Line ("Okuma hizi    : {0} MB/s" -f $readMBs) ($(if($st -eq 'PASS'){'Green'}else{'Yellow'}))
        Add-Result 'SSD' 'Okuma hizi' ("$readMBs MB/s") $st
    } catch { Write-Line "SSD hiz testi hatasi: $_" 'Red' }
    finally { if (Test-Path $tmp) { Remove-Item $tmp -Force -ErrorAction SilentlyContinue } }
}

# ======================================================================
#  OZET TABLO
# ======================================================================
Write-Head "OZET"
$fail = ($results | Where-Object Status -eq 'FAIL').Count
$warn = ($results | Where-Object Status -eq 'WARN').Count
foreach ($r in $results) {
    $c = switch ($r.Status) { 'PASS'{'Green'} 'FAIL'{'Red'} 'WARN'{'Yellow'} default{'Gray'} }
    $line = "[{0,-4}] {1,-10} {2,-22} {3}" -f $r.Status, $r.Category, $r.Item, $r.Value
    Write-Host $line -ForegroundColor $c
    $report.Add($line)
}
Write-Host ""
$verdict = if ($fail -gt 0) { "RED (FAIL)" } elseif ($warn -gt 0) { "SARTLI GECTI (WARN)" } else { "GECTI (PASS)" }
$vc = if ($fail -gt 0) {'Red'} elseif ($warn -gt 0) {'Yellow'} else {'Green'}
Write-Host "================================================================" -ForegroundColor $vc
Write-Host "  SONUC: $verdict     (FAIL=$fail  WARN=$warn)" -ForegroundColor $vc
Write-Host "================================================================" -ForegroundColor $vc
$report.Add(""); $report.Add("SONUC: $verdict  (FAIL=$fail WARN=$warn)")

# ======================================================================
#  RAPOR DOSYALARI
# ======================================================================
$stamp    = Get-Date -Format 'yyyyMMdd_HHmmss'
$baseName = "{0}_{1}" -f $env:COMPUTERNAME, $stamp
$txtPath  = Join-Path $BaseDir "$baseName.txt"
$report | Set-Content -Path $txtPath -Encoding UTF8
Write-Host "`nRapor: $txtPath" -ForegroundColor Cyan

if ($Html) {
    $rows = ($results | ForEach-Object {
        $cls = $_.Status.ToLower()
        "<tr class='$cls'><td>$($_.Status)</td><td>$($_.Category)</td><td>$($_.Item)</td><td>$($_.Value)</td></tr>"
    }) -join "`n"
    $htmlPath = Join-Path $BaseDir "$baseName.html"
    @"
<!doctype html><html><head><meta charset='utf-8'><title>PC Test - $env:COMPUTERNAME</title>
<style>body{font-family:Segoe UI,Arial;margin:24px}h1{font-size:20px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;padding:6px 10px;text-align:left}
th{background:#222;color:#fff}.pass{background:#e7f7e7}.fail{background:#fde2e2}.warn{background:#fff7df}.info{background:#fff}
.verdict{font-size:18px;font-weight:bold;padding:10px;margin:12px 0}</style></head><body>
<h1>Donanim Test Raporu</h1><p>$env:COMPUTERNAME &nbsp; $(Get-Date)</p>
<div class='verdict $(if($fail){'fail'}elseif($warn){'warn'}else{'pass'})'>SONUC: $verdict (FAIL=$fail WARN=$warn)</div>
<table><tr><th>Durum</th><th>Kategori</th><th>Test</th><th>Deger</th></tr>$rows</table></body></html>
"@ | Set-Content -Path $htmlPath -Encoding UTF8
    Write-Host "HTML : $htmlPath" -ForegroundColor Cyan
}

# Cikis kodu: FAIL varsa 1 (uretim hatti otomasyonu icin)
exit ([int]($fail -gt 0))
