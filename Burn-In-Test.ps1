<#
.SYNOPSIS
    Dokunmatik PC - uzun sureli BURN-IN / dayaniklilik (soak) testi.
    Varsayilan 2 saat tum cekirdekleri yukler, periyodik olcum alir,
    CSV'ye canli loglar ve sonunda GRAFIKLI HTML rapor uretir.

.DESCRIPTION
    Kurulum gerektirmez. Yonetici olarak calistirmak SMART/sicaklik ve
    WHEA donanim hatasi tespiti icin onerilir.
    Test kesilirse (Ctrl+C / elektrik) CSV'deki veriler korunur ve
    -FromCsv ile sonradan rapor yeniden uretilebilir.

.USAGE
    Yonetici PowerShell:
      Set-ExecutionPolicy -Scope Process Bypass -Force
      cd D:\pc-test-tool

      .\Burn-In-Test.ps1                       # 2 saat, 15 sn ornekleme
      .\Burn-In-Test.ps1 -DurationMinutes 30   # kisa deneme
      .\Burn-In-Test.ps1 -DurationMinutes 120 -SampleSeconds 10 -RamStressMB 1024
      .\Burn-In-Test.ps1 -FromCsv .\burnin_ENDU_20260527.csv   # eski logdan rapor uret

.NOTES
    Ciktilar: burnin_<PC>_<tarih>.csv  ve  burnin_<PC>_<tarih>.html (ayni klasor)
#>

[CmdletBinding()]
param(
    [int]    $DurationMinutes = 120,    # toplam test suresi (dk)
    [int]    $SampleSeconds    = 15,     # olcum araligi (sn)
    [int]    $RamStressMB      = 512,    # her cekirdek isciye dagitilan ek RAM yuku (0 = kapali)
    [int]    $MaxCpuTempC      = 95,     # bu sicakligi gecerse FAIL
    [string] $FromCsv          = ''      # verilirse: testi calistirmaz, sadece bu CSV'den HTML rapor uretir
)

$ErrorActionPreference = 'Continue'

# TR Windows ondalik ayraci virgul -> CSV/parse tutarsizligini engelle.
# Tum sayisal bicimleme ve [double] cast'leri nokta kullansin:
[System.Threading.Thread]::CurrentThread.CurrentCulture = [Globalization.CultureInfo]::InvariantCulture

# Rapor klasoru: .ps1 calisirken script klasoru, .exe (ps2exe) ise exe klasoru
$BaseDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent ([System.Diagnostics.Process]::GetCurrentProcess().MainModule.FileName) }

# ---------------------------------------------------------------------
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-CpuTempC {
    try {
        $t = Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | Select-Object -First 1
        if ($t) { return [math]::Round(($t.CurrentTemperature/10)-273.15,1) }
    } catch {}
    return $null
}

function Get-CpuLoadPct {
    # Locale-bagimsiz (TR Windows'ta Get-Counter sorun cikarir)
    try {
        $p = Get-CimInstance Win32_PerfFormattedData_PerfOS_Processor -Filter "Name='_Total'" -ErrorAction Stop
        return [int]$p.PercentProcessorTime
    } catch { return $null }
}

function Get-DiskTempC {
    try {
        $rc = Get-PhysicalDisk -ErrorAction Stop | Get-StorageReliabilityCounter -ErrorAction Stop | Select-Object -First 1
        if ($rc -and $rc.Temperature) { return [int]$rc.Temperature }
    } catch {}
    return $null
}

function Get-WheaErrorCount {
    param([datetime]$Since)
    try {
        $ev = Get-WinEvent -FilterHashtable @{
            LogName      = 'System'
            ProviderName = 'Microsoft-Windows-WHEA-Logger'
            StartTime    = $Since
        } -ErrorAction Stop
        return @($ev | Where-Object { $_.Level -le 3 }).Count   # 1=Critical 2=Error 3=Warning
    } catch { return 0 }   # kayit yoksa exception -> 0
}

function Get-RebootHistory {
    <# System olay gunlugunden kapanma/acilma olaylarini sinifa ayirir.
       Dondurur: zaman, tip (TEMIZ/SOFT-RESET/BEKLENMEDIK), aciklama #>
    param([datetime]$Since)
    $out = [System.Collections.Generic.List[object]]::new()
    try {
        $ids = 6005,6006,6008,1074,1076,41
        $ev = Get-WinEvent -FilterHashtable @{ LogName='System'; Id=$ids; StartTime=$Since } -ErrorAction Stop |
              Sort-Object TimeCreated
        foreach ($e in $ev) {
            $t=''; $d=''
            switch ($e.Id) {
                6006 { $t='TEMIZ KAPANMA';     $d='Duzgun kapatildi (shutdown).' }
                6005 { $t='ACILIS';            $d='Sistem acildi (event log basladi).' }
                6008 { $t='BEKLENMEDIK';       $d='Onceki kapanma duzgun degildi: ELEKTRIK KESINTISI veya HARD/MANUEL RESET.' }
                41   { $t='BEKLENMEDIK (Kernel-Power)'; $d='Sistem duzgun kapanmadan yeniden basladi: elektrik/hard-reset/crash.' }
                1074 { $t='SOFT-RESET/KAPANMA'; $d='Kullanici ya da OS baslatti (planli reboot/shutdown). ' + ($e.Message -split "`n" | Select-Object -First 1) }
                1076 { $t='BEKLENMEDIK (neden)'; $d=($e.Message -split "`n" | Select-Object -First 1) }
            }
            $out.Add([pscustomobject]@{ Time=$e.TimeCreated; Id=$e.Id; Type=$t; Detail=$d })
        }
    } catch {}
    return $out
}

# =====================================================================
#  SADECE RAPOR URETIMI  (-FromCsv)
# =====================================================================
function Build-Report {
    param([string]$CsvPath,[string]$HtmlPath,[hashtable]$Meta)

    $rows = Import-Csv $CsvPath
    if (-not $rows) { Write-Host "CSV bos: $CsvPath" -ForegroundColor Red; return }

    $loads = $rows | ForEach-Object { [double]$_.CpuLoad } | Where-Object { $_ -ne $null }
    $temps = $rows | Where-Object { $_.CpuTempC -ne '' -and $_.CpuTempC -ne 'NA' } | ForEach-Object { [double]$_.CpuTempC }
    $clocks= $rows | ForEach-Object { [double]$_.CpuClockMHz } | Where-Object { $_ -gt 0 }
    $dtemps= $rows | Where-Object { $_.DiskTempC -ne '' -and $_.DiskTempC -ne 'NA' } | ForEach-Object { [double]$_.DiskTempC }
    $whea  = ($rows | Measure-Object -Property WheaErrors -Maximum).Maximum

    function Stat($a){ if($a.Count){ "{0:n0} / {1:n0} / {2:n0}" -f ($a|Measure-Object -Minimum).Minimum,(($a|Measure-Object -Average).Average),($a|Measure-Object -Maximum).Maximum } else {'-'} }

    $maxTemp = if ($temps.Count) { ($temps|Measure-Object -Maximum).Maximum } else { $null }
    $maxLoadOK = if ($loads.Count) { (($loads|Measure-Object -Average).Average) -ge 70 } else { $false }

    # --- test penceresinde reset/kapanma olaylari
    $reboots = @()
    if ($Meta.RebootSince) { $reboots = @(Get-RebootHistory -Since $Meta.RebootSince) }
    $unexpected = @($reboots | Where-Object { $_.Type -like 'BEKLENMEDIK*' }).Count

    # --- verdict
    $fails = @()
    if ($whea -gt 0)                                  { $fails += "WHEA donanim hatasi: $whea adet" }
    if ($maxTemp -and $maxTemp -gt $Meta.MaxCpuTempC) { $fails += "CPU max sicaklik $maxTemp C (limit $($Meta.MaxCpuTempC))" }
    if ($unexpected -gt 0)                            { $fails += "Test sirasinda $unexpected beklenmedik reset/elektrik kesintisi!" }
    $verdict = if ($fails.Count) { 'FAIL' } else { 'PASS' }

    $rebootHtml = if ($reboots.Count) {
        $rr = ($reboots | ForEach-Object {
            $cls = if ($_.Type -like 'BEKLENMEDIK*') {'fail'} elseif ($_.Type -like 'SOFT*') {'warn'} else {''}
            "<tr class='$cls'><td>$($_.Time.ToString('yyyy-MM-dd HH:mm:ss'))</td><td>$($_.Type)</td><td>$($_.Detail)</td></tr>"
        }) -join ''
        "<table><tr><th>Zaman</th><th>Tip</th><th>Aciklama</th></tr>$rr</table>"
    } else { "<p class='mut'>Test penceresinde kapanma/reset olayi yok.</p>" }

    # --- SVG cizgi grafik uretici
    function New-Svg {
        param([double[]]$Data,[string]$Color,[string]$Title,[double]$Min,[double]$Max)
        if (-not $Data.Count) { return "<p>$Title : veri yok</p>" }
        $w=900; $h=180; $pad=30
        if ($Max -le $Min) { $Max = $Min + 1 }
        $n = $Data.Count
        $pts = for ($i=0;$i -lt $n;$i++) {
            $x = $pad + ($i/[math]::Max(1,$n-1))*($w-2*$pad)
            $y = $h-$pad - (($Data[$i]-$Min)/($Max-$Min))*($h-2*$pad)
            "{0:n1},{1:n1}" -f $x,$y
        }
        $poly = $pts -join ' '
        $yTop = $h-$pad - (($Max-$Min)/($Max-$Min))*($h-2*$pad)
        @"
<div class='chart'><b>$Title</b> &nbsp; <span class='mut'>(min $($Min) - max $($Max))</span>
<svg width='100%' viewBox='0 0 $w $h' preserveAspectRatio='none'>
<rect x='0' y='0' width='$w' height='$h' fill='#0d1117'/>
<line x1='$pad' y1='$($h-$pad)' x2='$($w-$pad)' y2='$($h-$pad)' stroke='#30363d'/>
<line x1='$pad' y1='$pad' x2='$pad' y2='$($h-$pad)' stroke='#30363d'/>
<polyline points='$poly' fill='none' stroke='$Color' stroke-width='2'/>
</svg></div>
"@
    }

    $tMin = if($temps.Count){[math]::Floor((($temps|Measure-Object -Minimum).Minimum)-2)}else{0}
    $tMax = if($temps.Count){[math]::Ceiling((($temps|Measure-Object -Maximum).Maximum)+2)}else{1}
    $cMin = if($clocks.Count){[math]::Floor((($clocks|Measure-Object -Minimum).Minimum)-100)}else{0}
    $cMax = if($clocks.Count){[math]::Ceiling((($clocks|Measure-Object -Maximum).Maximum)+100)}else{1}

    $svgLoad  = New-Svg -Data $loads  -Color '#3fb950' -Title 'CPU Yuku (%)'        -Min 0 -Max 100
    $svgTemp  = New-Svg -Data $temps  -Color '#f85149' -Title 'CPU Sicaklik (C)'    -Min $tMin -Max $tMax
    $svgClock = New-Svg -Data $clocks -Color '#58a6ff' -Title 'CPU Saat (MHz) - dususler throttle' -Min $cMin -Max $cMax

    $failHtml = if($fails.Count){ "<ul>"+(($fails|ForEach-Object{"<li>$_</li>"}) -join '')+"</ul>" } else { "Tum kriterler gecti." }

    $startStr = $Meta.Start; $dur = $Meta.DurationMin; $samples = $rows.Count
    @"
<!doctype html><html><head><meta charset='utf-8'><title>Burn-In Raporu</title>
<style>
body{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,Arial;margin:24px}
h1{font-size:22px}.mut{color:#8b949e}
table{border-collapse:collapse;margin:14px 0}td,th{border:1px solid #30363d;padding:6px 14px;text-align:left}
th{background:#161b22}.chart{margin:18px 0}
.verdict{font-size:20px;font-weight:bold;padding:12px 18px;border-radius:8px;margin:14px 0;display:inline-block}
.pass{background:#0f3d1f;color:#3fb950}.fail{background:#4d1414;color:#f85149}
</style></head><body>
<h1>Burn-In / Dayaniklilik Test Raporu</h1>
<p class='mut'>$($Meta.Computer) &nbsp;|&nbsp; Baslangic: $startStr &nbsp;|&nbsp; Hedef sure: $dur dk &nbsp;|&nbsp; $samples olcum</p>
<div class='verdict $($verdict.ToLower())'>SONUC: $verdict</div>
<div>$failHtml</div>
<table>
<tr><th>Metrik</th><th>min / ort / max</th></tr>
<tr><td>CPU Yuku (%)</td><td>$(Stat $loads)</td></tr>
<tr><td>CPU Sicaklik (C)</td><td>$(Stat $temps)</td></tr>
<tr><td>CPU Saat (MHz)</td><td>$(Stat $clocks)</td></tr>
<tr><td>Disk Sicaklik (C)</td><td>$(Stat $dtemps)</td></tr>
<tr><td>WHEA donanim hatasi</td><td>$whea</td></tr>
<tr><td>Beklenmedik reset/elektrik</td><td>$unexpected</td></tr>
</table>
<h2>Kapanma / Reset Gecmisi (test penceresi)</h2>
$rebootHtml
$svgLoad
$svgTemp
$svgClock
<p class='mut'>Ham veri: $(Split-Path $CsvPath -Leaf)</p>
</body></html>
"@ | Set-Content -Path $HtmlPath -Encoding UTF8
    Write-Host "HTML rapor: $HtmlPath" -ForegroundColor Cyan
    return $verdict
}

# =====================================================================
#  -FromCsv: sadece rapor uret, cik
# =====================================================================
if ($FromCsv) {
    if (-not (Test-Path $FromCsv)) { Write-Host "Bulunamadi: $FromCsv" -ForegroundColor Red; exit 2 }
    $html = [IO.Path]::ChangeExtension((Resolve-Path $FromCsv).Path, '.html')
    Build-Report -CsvPath (Resolve-Path $FromCsv).Path -HtmlPath $html `
                 -Meta @{ Computer=$env:COMPUTERNAME; Start='(logdan)'; DurationMin='?'; MaxCpuTempC=$MaxCpuTempC } | Out-Null
    Start-Process $html
    exit 0
}

# =====================================================================
#  TEST CALISTIR
# =====================================================================
try { Clear-Host } catch {}
$start    = Get-Date
$stamp    = $start.ToString('yyyyMMdd_HHmmss')
$csvPath  = Join-Path $BaseDir ("burnin_{0}_{1}.csv"  -f $env:COMPUTERNAME,$stamp)
$htmlPath = Join-Path $BaseDir ("burnin_{0}_{1}.html" -f $env:COMPUTERNAME,$stamp)
$endTime  = $start.AddMinutes($DurationMinutes)
$cores    = [Environment]::ProcessorCount

Write-Host "================================================================" -ForegroundColor White
Write-Host "      BURN-IN / DAYANIKLILIK TESTI" -ForegroundColor White
Write-Host "      $env:COMPUTERNAME   |   $cores is parcacigi   |   $DurationMinutes dk" -ForegroundColor White
Write-Host "      Baslangic: $($start.ToString('HH:mm:ss'))   Bitis(hedef): $($endTime.ToString('HH:mm:ss'))" -ForegroundColor White
Write-Host "================================================================" -ForegroundColor White
if (-not (Test-Admin)) { Write-Host "[!] Yonetici degil - sicaklik/SMART/WHEA eksik olabilir.`n" -ForegroundColor Yellow }

# CSV basligi
"Timestamp,ElapsedMin,CpuLoad,CpuClockMHz,CpuTempC,RamUsedPct,DiskTempC,WheaErrors" |
    Set-Content -Path $csvPath -Encoding UTF8

$maxClock = (Get-CimInstance Win32_Processor | Select-Object -First 1).MaxClockSpeed
$wheaBase = $start   # bu andan sonraki WHEA hatalari sayilir

# --- CPU yuk iscileri (tum sure boyunca) + opsiyonel RAM yuku
$perCoreRamMB = if ($RamStressMB -gt 0) { [math]::Floor($RamStressMB/$cores) } else { 0 }
Write-Host "Yuk iscileri baslatiliyor ($cores cekirdek, cekirdek basina $perCoreRamMB MB RAM)..." -ForegroundColor Gray
$jobs = 1..$cores | ForEach-Object {
    Start-Job -ScriptBlock {
        param($endTicks,$ramMB)
        $end = [datetime]::new($endTicks)
        $hold = if ($ramMB -gt 0) {
            $a = [byte[]]::new($ramMB*1MB); for($i=0;$i -lt $a.Length;$i+=4096){$a[$i]=1}; ,$a
        } else { $null }
        $x = 0.0001
        while ((Get-Date) -lt $end) {
            for ($k=0;$k -lt 200000;$k++) { $x = [math]::Sqrt($x*3.14159)+[math]::Sin($x); $x += 0.0001 }
            if ($hold) { $hold[0][0] = ($hold[0][0]+1) % 250 }   # RAM'i sicak tut
        }
    } -ArgumentList $endTime.Ticks,$perCoreRamMB
}

$sampleCount = 0
$peakTemp = 0; $peakLoad = 0; $minClock = $maxClock
$cleanExit = $false
try {
    while ((Get-Date) -lt $endTime) {
        Start-Sleep -Seconds $SampleSeconds
        $now      = Get-Date
        $elapsed  = [math]::Round(($now-$start).TotalMinutes,2)
        $load     = Get-CpuLoadPct
        $clock    = (Get-CimInstance Win32_Processor | Select-Object -First 1).CurrentClockSpeed
        $temp     = Get-CpuTempC
        $os       = Get-CimInstance Win32_OperatingSystem
        $ramUsed  = [math]::Round(100*(1-($os.FreePhysicalMemory/$os.TotalVisibleMemorySize)),0)
        $dtemp    = Get-DiskTempC
        $whea     = Get-WheaErrorCount -Since $wheaBase

        $tempStr  = if ($temp -ne $null) { $temp } else { 'NA' }
        $dtempStr = if ($dtemp -ne $null) { $dtemp } else { 'NA' }
        "{0},{1},{2},{3},{4},{5},{6},{7}" -f $now.ToString('yyyy-MM-dd HH:mm:ss'),$elapsed,$load,$clock,$tempStr,$ramUsed,$dtempStr,$whea |
            Add-Content -Path $csvPath -Encoding UTF8

        if ($temp -ne $null -and $temp -gt $peakTemp) { $peakTemp = $temp }
        if ($load -ne $null -and $load -gt $peakLoad) { $peakLoad = $load }
        if ($clock -lt $minClock) { $minClock = $clock }
        $sampleCount++

        $pct  = [math]::Min(100,[math]::Round(($now-$start).TotalSeconds/($DurationMinutes*60)*100,1))
        $tShow = if ($temp -ne $null) { "$temp C" } else { "N/A" }
        $remain = [math]::Round(($endTime-$now).TotalMinutes,0)
        $whCol = if ($whea -gt 0) {'Red'} else {'Gray'}
        Write-Host ("[{0,5}%] gecen {1,5} dk | yuk %{2,3} | saat {3} MHz | sicaklik {4} | RAM %{5} | WHEA {6} | kalan ~{7} dk" -f `
            $pct,$elapsed,$load,$clock,$tShow,$ramUsed,$whea,$remain) -ForegroundColor $whCol
        Write-Progress -Activity "Burn-In" -Status "$pct% - kalan ~$remain dk - peak temp $peakTemp C" -PercentComplete $pct
    }
    $cleanExit = $true
}
finally {
    Write-Progress -Activity "Burn-In" -Completed
    Write-Host "`nYuk iscileri durduruluyor..." -ForegroundColor Gray
    $jobs | Stop-Job  -ErrorAction SilentlyContinue
    $jobs | Remove-Job -Force -ErrorAction SilentlyContinue

    Write-Host ("Olcum sayisi: {0}   Peak yuk: %{1}   Peak CPU temp: {2} C   Min saat: {3} MHz (max {4})" -f `
        $sampleCount,$peakLoad,$(if($peakTemp){"$peakTemp"}else{"N/A"}),$minClock,$maxClock) -ForegroundColor Cyan
    if (-not $cleanExit) { Write-Host "[!] Test erken kesildi - CSV'deki veri korundu." -ForegroundColor Yellow }

    $verdict = Build-Report -CsvPath $csvPath -HtmlPath $htmlPath -Meta @{
        Computer=$env:COMPUTERNAME; Start=$start.ToString('yyyy-MM-dd HH:mm:ss')
        DurationMin=$DurationMinutes; MaxCpuTempC=$MaxCpuTempC; RebootSince=$start }

    Write-Host "`nCSV : $csvPath"  -ForegroundColor Cyan
    Write-Host "HTML: $htmlPath"   -ForegroundColor Cyan
    $vc = if ($verdict -eq 'FAIL') {'Red'} else {'Green'}
    Write-Host "`n  SONUC: $verdict`n" -ForegroundColor $vc
    try { Start-Process $htmlPath } catch {}
}

exit ([int]($verdict -eq 'FAIL'))
