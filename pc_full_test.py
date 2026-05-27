# -*- coding: utf-8 -*-
"""
DOKUNMATIK PC - TEK EXE  TUM TESTLER (otomatik sihirbaz)
========================================================
Acilinca sırayla:
  1) EKRAN testi (renk / dead-pixel / gradyan)        [operatör: GEÇTİ/HATALI]
  2) DOKUNMATIK çizim testi                            [operatör: GEÇTİ/HATALI]
  3) DOKUNMATIK izgara kapsama (her hücreye dokun)     [otomatik gecer]
  4) Donanım envanteri (CPU/RAM/Disk/SMART/GPU)        [otomatik]
  5) CPU/RAM stres                                     [otomatik]
  6) SSD hız (oku/yaz)                                 [otomatik]
  7) Ağ (Ethernet/WiFi + internet ping)               [otomatik]
  8) OZET + rapor (TXT/HTML exe klasorune yazilir)

Donanım/stres testleri icin Windows'ta PowerShell + WMI kullanilir
(SMART/sıcaklık icin Yonetici önerilir). Ekran/dokunmatik saf tkinter.

Test (GUI'siz):  python pc_full_test.py --selftest
"""

import os, sys, time, json, math, threading, tempfile, subprocess, base64
from datetime import datetime as _dt
import multiprocessing as mp
import tkinter as tk
from tkinter import ttk

APP_VERSION = "1.1"

# ======================= AYARLAR (uretim hatti) =======================
EXPECTED = {
    "min_ram_gb":      4,
    "min_disk_gb":     100,
    "min_ssd_write":   80,    # MB/s
    "min_ssd_read":    150,   # MB/s
    "max_cpu_temp":    95,    # C (okunabilirse)
    "stress_seconds":  45,    # CPU/RAM stres süresi
    "ssd_test_mb":     256,
    "ram_test_mb":     256,
}

CREATE_NO_WINDOW = 0x08000000


# ======================= PowerShell yardimcilari ======================
def run_ps(script, timeout=120):
    pre = ("[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
           "[Threading.Thread]::CurrentThread.CurrentCulture="
           "[Globalization.CultureInfo]::InvariantCulture;"
           "$ErrorActionPreference='SilentlyContinue';")
    try:
        p = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
             "-Command", pre + script],
            capture_output=True, timeout=timeout, creationflags=CREATE_NO_WINDOW)
        return p.stdout.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def ps_json(script, timeout=120):
    out = run_ps(script, timeout)
    if not out:
        return None
    try:
        return json.loads(out)
    except Exception:
        return None


PS_INVENTORY = r"""
$cpu=Get-CimInstance Win32_Processor|Select-Object -First 1
$bb=Get-CimInstance Win32_BaseBoard
$bios=Get-CimInstance Win32_BIOS
$os=Get-CimInstance Win32_OperatingSystem
$ramgb=[math]::Round(((Get-CimInstance Win32_PhysicalMemory|Measure-Object Capacity -Sum).Sum)/1GB,0)
$disks=@(Get-PhysicalDisk|ForEach-Object{
  $rc=$_|Get-StorageReliabilityCounter -ErrorAction SilentlyContinue
  [pscustomobject]@{name=$_.FriendlyName;gb=[math]::Round($_.Size/1GB,0);media="$($_.MediaType)";bus="$($_.BusType)";health="$($_.HealthStatus)";
    temp=$rc.Temperature;wear=$rc.Wear;readErr=$rc.ReadErrorsTotal;writeErr=$rc.WriteErrorsTotal;poh=$rc.PowerOnHours}})
$sys=Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$res=Get-CimInstance Win32_VideoController|Where-Object{$_.CurrentHorizontalResolution}|Select-Object -First 1
[pscustomobject]@{
  computer=$env:COMPUTERNAME
  board="$($bb.Manufacturer) $($bb.Product)"
  serial="$($bios.SerialNumber)"
  bios="$($bios.Manufacturer) $($bios.SMBIOSBIOSVersion)"
  bios_year=$(try{$bios.ReleaseDate.Year}catch{0})
  sysyear=(Get-Date).Year
  os_install=$(try{$os.InstallDate.ToString('yyyy-MM-dd')}catch{''})
  os="$($os.Caption) $($os.OSArchitecture)"
  cpu=$cpu.Name.Trim(); cores=$cpu.NumberOfCores; threads=$cpu.NumberOfLogicalProcessors
  ramgb=$ramgb
  rambanks=@(Get-CimInstance Win32_PhysicalMemory).Count
  sysdisk_gb=[math]::Round($sys.Size/1GB,0)
  sysfree_gb=[math]::Round($sys.FreeSpace/1GB,0)
  disks=$disks
  gpu=((Get-CimInstance Win32_VideoController|Select-Object -ExpandProperty Name) -join '; ')
  res=$(if($res){"$($res.CurrentHorizontalResolution)x$($res.CurrentVerticalResolution)@$($res.CurrentRefreshRate)Hz"}else{''})
}|ConvertTo-Json -Depth 5 -Compress
"""

PS_NETWORK = r"""
$ad=@(Get-NetAdapter|Where-Object{$_.HardwareInterface}|ForEach-Object{
  [pscustomobject]@{name=$_.Name;desc=$_.InterfaceDescription;status="$($_.Status)";
    mbps=$(if($_.Status -eq 'Up' -and $_.ReceiveLinkSpeed){[math]::Round($_.ReceiveLinkSpeed/1e6,0)}else{0});mac=$_.MacAddress}})
$ping=$null
try{$p=Test-Connection 8.8.8.8 -Count 3 -ErrorAction Stop;$ping=[math]::Round(($p|Measure-Object ResponseTime -Average).Average,0)}catch{}
[pscustomobject]@{adapters=$ad;pingms=$ping}|ConvertTo-Json -Depth 5 -Compress
"""

PS_DISKSCAN = r"""
$dl=$env:SystemDrive.TrimEnd(':')
$dirty='NA'
try{
  $o=cmd /c "fsutil dirty query $env:SystemDrive" 2>$null
  if($o -match 'NOT Dirty'){$dirty='temiz'} elseif($o -match 'is Dirty'){$dirty='KIRLI'}
}catch{}
$scan='NA'
try{$scan="$(Repair-Volume -DriveLetter $dl -Scan -ErrorAction Stop)"}catch{$scan='NA'}
[pscustomobject]@{dirty=$dirty;scan=$scan}|ConvertTo-Json -Compress
"""

PS_TEMP = r"""
$t=Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue|Select-Object -First 1
if($t){[math]::Round(($t.CurrentTemperature/10)-273.15,1)}else{'NA'}
"""

# yük altında: sıcaklık + CPU saati (throttle) + pil/adaptör durumu (tek cagri)
PS_LOADSTAT = r"""
$t=Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue|Select-Object -First 1
$temp=if($t){[math]::Round(($t.CurrentTemperature/10)-273.15,1)}else{$null}
$c=Get-CimInstance Win32_Processor|Select-Object -First 1
$b=Get-CimInstance Win32_Battery -ErrorAction SilentlyContinue|Select-Object -First 1
[pscustomobject]@{temp=$temp;clock=$c.CurrentClockSpeed;maxclock=$c.MaxClockSpeed;
  batt=$(if($b){[int]$b.BatteryStatus}else{$null});batt_present=[bool]$b}|ConvertTo-Json -Compress
"""


def get_loadstat():
    return ps_json(PS_LOADSTAT, timeout=20) or {}


# cipset/sürücü + USB + voltaj + isi bölgeleri sağlık taramasi
PS_HEALTH = r"""
$prob=@(Get-CimInstance Win32_PnPEntity -Filter "ConfigManagerErrorCode<>0 AND ConfigManagerErrorCode IS NOT NULL" -ErrorAction SilentlyContinue|
  ForEach-Object{[pscustomobject]@{name="$($_.Name)";code=[int]$_.ConfigManagerErrorCode}})
$usbc=@(Get-CimInstance Win32_USBController -ErrorAction SilentlyContinue).Count
$usbprob=@($prob|Where-Object{$_.name -match 'USB|Universal Serial'}).Count
$cv=(Get-CimInstance Win32_Processor|Select-Object -First 1).CurrentVoltage
$volt=$(if($cv -and ($cv -band 0x80)){[math]::Round(($cv -band 0x7f)/10,1)}else{$null})
$tz=@(Get-CimInstance -Namespace root/wmi MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue|
  ForEach-Object{[math]::Round(($_.CurrentTemperature/10)-273.15,1)})
[pscustomobject]@{problems=$prob;usb_ctrl=$usbc;usb_prob=$usbprob;volt=$volt;zones=$tz}|ConvertTo-Json -Depth 4 -Compress
"""


def cpu_bench(seconds=1.5):
    """Tek çekirdek performans indeksi (op/s) — yük yokken ölçülür."""
    end = time.time() + seconds
    n = 0
    x = 0.0001
    while time.time() < end:
        for _ in range(2000):
            x = math.sqrt(abs(x) * 3.14159) + math.sin(x)
            x += 0.0001
        n += 2000
    return int(n / seconds)

PS_USBEVENTS = r"""
$since=(Get-Date).AddDays(-90)
$prov='Microsoft-Windows-Kernel-PnP','Microsoft-Windows-Kernel-PnPMgr','usbhub','UsbHub3','USBHUB3','Microsoft-Windows-USB-USBHUB3'
$ev=@()
foreach($p in $prov){ try{$ev+=Get-WinEvent -FilterHashtable @{LogName='System';ProviderName=$p;StartTime=$since} -ErrorAction Stop}catch{} }
$surge=@(); $fault=@()
foreach($e in $ev){
  $m="$($e.Message)"
  if($m -match 'power surge|exceeded the power limit|over-?current|surge on'){
    $surge+=[pscustomobject]@{time=$e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');msg=(($m -split "`r?`n")|Where-Object{$_}|Select-Object -First 1)}
  } elseif($m -match 'malfunction|not recognized|failed to start|cannot start|descriptor request failed|surprise|unexpectedly removed'){
    $fault+=[pscustomobject]@{time=$e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');msg=(($m -split "`r?`n")|Where-Object{$_}|Select-Object -First 1)}
  }
}
[pscustomobject]@{surge=$surge;fault=$fault}|ConvertTo-Json -Depth 4 -Compress
"""

PS_CRITICAL = r"""
$since=(Get-Date).AddDays(-90)
$whea=0
try{$whea=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName='Microsoft-Windows-WHEA-Logger';StartTime=$since} -ErrorAction Stop|Where-Object{$_.Level -le 3}).Count}catch{}
$diskerr=0
foreach($p in 'disk','Disk','Ntfs','volmgr','storahci','stornvme','iaStorA'){
  try{$diskerr+=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName=$p;Level=1,2;StartTime=$since} -ErrorAction Stop).Count}catch{}
}
$bsod=0
foreach($pp in @(@{p='Microsoft-Windows-WER-SystemErrorReporting';i=1001},@{p='BugCheck';i=1001})){
  try{$bsod+=@(Get-WinEvent -FilterHashtable @{LogName='System';ProviderName=$pp.p;Id=$pp.i;StartTime=$since} -ErrorAction Stop).Count}catch{}
}
$oldest=''
try{$o=Get-WinEvent -LogName System -MaxEvents 1 -Oldest -ErrorAction Stop;$oldest=$o.TimeCreated.ToString('yyyy-MM-dd')}catch{}
[pscustomobject]@{whea=$whea;diskerr=$diskerr;bsod=$bsod;log_oldest=$oldest}|ConvertTo-Json -Compress
"""

PS_RESET_HIST = r"""
$since=(Get-Date).AddDays(-90)
$ev=@()
try{$ev=Get-WinEvent -FilterHashtable @{LogName='System';Id=6005,6006,6008,1074,1076,41;StartTime=$since} -ErrorAction Stop|Sort-Object TimeCreated}catch{}
$out=foreach($e in $ev){
 $t='';$d=''
 switch($e.Id){
  6006{$t='TEMIZ';$d='Düzgün kapatıldı'}
  6005{$t='ACILIS';$d='Sistem açıldı'}
  6008{$t='BEKLENMEDIK';$d='Elektrik kesintisi veya manuel/hard-reset'}
  41  {$t='BEKLENMEDIK';$d='Kernel-Power 41: düzgün kapanmadan yeniden başladi'}
  1074{$t='SOFT';$d=(($e.Message -split "`r?`n")|Where-Object{$_}|Select-Object -First 1)}
  1076{$t='BEKLENMEDIK';$d=(($e.Message -split "`r?`n")|Where-Object{$_}|Select-Object -First 1)}
 }
 [pscustomobject]@{time=$e.TimeCreated.ToString('yyyy-MM-dd HH:mm:ss');type=$t;detail=($d -replace '\s+',' ').Trim()}
}
@($out)|ConvertTo-Json -Depth 4 -Compress
"""


def read_temp():
    out = run_ps(PS_TEMP, timeout=20)
    try:
        return float(out)
    except Exception:
        return None


# ======================= CPU stres iscisi (top-level) =================
def _cpu_worker(seconds):
    end = time.time() + seconds
    x = 0.0001
    while time.time() < end:
        for _ in range(60000):
            x = math.sqrt(abs(x) * 3.14159) + math.sin(x)
            x += 0.0001


def ram_verify(mb):
    n = mb * 1024 * 1024
    a = bytearray(n)
    for i in range(0, n, 4096):
        a[i] = 0xAA
    ok = all(a[i] == 0xAA for i in range(0, n, 4096))
    for i in range(0, n, 4096):
        a[i] = 0x55
    ok = ok and all(a[i] == 0x55 for i in range(0, n, 4096))
    del a
    return ok


def ssd_speed(size_mb):
    """Yaz/oku hızı + VERI BUTUNLUGU doğrulaması. Doner: (write, read, integrity_ok)."""
    fn = os.path.join(tempfile.gettempdir(), "pctest_ssd.bin")
    chunk = 8 * 1024 * 1024
    buf = os.urandom(chunk)
    loops = max(1, size_mb // 8)
    integrity_ok = True
    try:
        t = time.time()
        with open(fn, "wb", buffering=0) as f:
            for _ in range(loops):
                f.write(buf)
            f.flush()
            os.fsync(f.fileno())
        write = (loops * 8) / (time.time() - t)
        t = time.time()
        with open(fn, "rb", buffering=0) as f:
            while True:
                d = f.read(chunk)
                if not d:
                    break
                # geri okunan veri yazilanla birebir mi? (bozuk/zayif blok yakalar)
                if d != buf[:len(d)]:
                    integrity_ok = False
        read = (loops * 8) / (time.time() - t)
        return round(write, 1), round(read, 1), integrity_ok
    finally:
        try:
            os.remove(fn)
        except Exception:
            pass


def count_unexpected(events, window_sec=120):
    """Beklenmedik kapanmalari TEKLESTIR: ayni kirli kapanma hem Kernel-Power 41
    hem 6008 uretir (saniyeler arayla) -> tek olay say."""
    times = []
    for e in events:
        if e.get("type") == "BEKLENMEDIK":
            try:
                times.append(_dt.strptime(e.get("time", ""), "%Y-%m-%d %H:%M:%S"))
            except Exception:
                pass
    times.sort()
    n, last = 0, None
    for t in times:
        if last is None or (t - last).total_seconds() > window_sec:
            n += 1
        last = t
    return n


def base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def resource_path(name):
    """exe yanindaki dosya oncelikli (kullanici değiştirebilir), sonra gomulu kaynak."""
    p = os.path.join(base_dir(), name)
    if os.path.exists(p):
        return p
    if getattr(sys, "frozen", False):
        mp_ = os.path.join(getattr(sys, "_MEIPASS", base_dir()), name)
        if os.path.exists(mp_):
            return mp_
    return p


def logo_data_uri():
    try:
        with open(resource_path("logo.png"), "rb") as f:
            return "data:image/png;base64," + base64.b64encode(f.read()).decode()
    except Exception:
        return ""


# ============================ GUI SIHIRBAZ ============================
BG = "#0d1117"; PANEL = "#161b22"; FG = "#c9d1d9"; ACC = "#58a6ff"
GREEN = "#3fb950"; RED = "#f85149"; YEL = "#d29922"; MUT = "#8b949e"

PALETTE = [("Kırmızı", "#FF0000"), ("Yeşil", "#00FF00"), ("Mavi", "#0000FF"),
           ("Beyaz", "#FFFFFF"), ("Siyah", "#000000"), ("Gri %50", "#808080")]

# 4 seviyeli derecelendirme (donanımin KENDI karakteristiğine gore)
GRADE_LABELS = ["ÇOK KÖTÜ", "KÖTÜ", "İYİ", "SÜPER"]
GRADE_COLORS = ["#f85149", "#e8833a", "#3fb950", "#2dd4bf"]


def disk_speed_baseline(bus, media):
    """Medya/bus tipine gore beklenen (write, read) MB/s -> yas/teknolojiye gore adil."""
    b = (str(bus) + " " + str(media)).lower()
    if "nvme" in b:
        return 700, 1500
    if "ssd" in b:                 # SATA SSD
        return 250, 350
    if "hdd" in b or "spin" in b:  # mekanik disk: bu kadari NORMAL, daha fazlasi beklenmez
        return 60, 90
    return 150, 250                # bilinmiyor: SATA SSD'ye yakın varsay


class Wizard:
    def __init__(self, root):
        self.root = root
        root.title("Dokunmatik PC - Tum Testler")
        root.configure(bg=BG)
        # PENCERE MODU (tam ekran değil) - baslik çubuğu + X tusu var, 1024x768'e sigar
        root.geometry("1000x720")
        root.minsize(820, 600)
        try:
            root.state("normal")
        except Exception:
            pass
        self._fs = False
        root.bind("<F11>", self._toggle_fs)          # F11: tam ekran ac/kapat (dead-pixel icin)
        root.bind("<F10>", lambda e: self._quit())   # acil çıkış
        root.bind("<Configure>", self._on_resize)

        self.rows = []          # rapor satirlari: (kategori,test,deger,durum)
        self.inv = None
        self.reset_events = []
        self.risks = []         # saha risk uyarilari
        self.stress_sec = EXPECTED["stress_seconds"]   # intro'da secilir
        self.stress_peak = None
        self.stress_csv = None
        self.minutes_var = tk.StringVar(value="1")
        self.op_var = tk.StringVar(value="")     # operatör adi
        self.sn_var = tk.StringVar(value="")     # seri no / iş emri
        self.grades = {}                         # donanım -> 0..3 (karakteristige gore)
        self.sys_bus = ""; self.sys_media = ""   # sistem diski bus/media (hız derecesi icin)
        self.health = {}                         # cipset/usb/voltaj/isi sağlık verisi
        self.usb_events = {}                     # usb güç/arıza olaylari (reset raporu)
        self.critical = {}                       # WHEA/disk/BSOD + log kapsami
        self.reset_unexp = 0                     # teklestirilmis beklenmedik kapanma sayisi

        # ttk profesyonel stil
        try:
            self.style = ttk.Style()
            self.style.theme_use("clam")
            self.style.configure("Green.Horizontal.TProgressbar", troughcolor=PANEL,
                                  background=GREEN, bordercolor=PANEL, lightcolor=GREEN, darkcolor=GREEN)
            self.style.configure("Blue.Horizontal.TProgressbar", troughcolor=PANEL,
                                  background=ACC, bordercolor=PANEL, lightcolor=ACC, darkcolor=ACC)
        except Exception:
            self.style = None
        root.title(f"Endutek PC Test  v{APP_VERSION}")
        try:
            if self.__dict__.get("logo"):
                root.iconphoto(True, self.logo)
        except Exception:
            pass
        self._update_clock()

        # hangi testler yapilacak (intro'da tiklenir) - 'done' her zaman çalışır
        self.enabled = {k: tk.BooleanVar(value=True)
                        for k in ("screen", "touch", "grid", "inv", "stress", "ssd", "net", "reset")}
        self.step_state = {}    # key -> 'PASS'/'FAIL'/'WARN'/'...'
        self.sw, self.sh = 1000, 720             # pencere ic olculeri (Configure ile guncellenir)

        # Endutek logosu (exe yaninda ya da gomulu logo.png) - sadece kenar çubuğunda
        self.logo = None
        try:
            lp = resource_path("logo.png")
            if os.path.exists(lp):
                self.logo = tk.PhotoImage(file=lp)
        except Exception:
            self.logo = None

        self.sequence = [
            ("screen", "1. Ekran (renk / dead-pixel)", self.step_screen),
            ("touch",  "2. Dokunmatik çizim",          self.step_touch),
            ("grid",   "3. Dokunmatik kapsama",        self.step_grid),
            ("inv",    "4. Donanım envanteri",         self.step_inventory),
            ("stress", "5. CPU / RAM stres",           self.step_stress),
            ("ssd",    "6. SSD hız",                   self.step_ssd),
            ("net",    "7. Ağ / internet",             self.step_network),
            ("reset",  "8. Reset / elektrik geçmişi",  self.step_reset),
            ("done",   "9. Ozet & rapor",              self.step_summary),
        ]
        self.i = -1
        self._intro()

    # ---------- iskelet ----------
    def _shell(self):
        for w in self.root.winfo_children():
            w.destroy()
        bar = tk.Frame(self.root, bg=PANEL, width=300)
        bar.pack(side="left", fill="y")
        bar.pack_propagate(False)
        tk.Label(bar, text="TEST ADIMLARI", font=("Segoe UI", 15, "bold"),
                 fg=ACC, bg=PANEL).pack(pady=(22, 16))
        for k, title, _ in self.sequence:
            disabled = (k in self.enabled and not self.enabled[k].get())
            st = self.step_state.get(k, "")
            mark = {"PASS": "✓", "FAIL": "✗", "WARN": "!", "RUN": "•"}.get(st, "")
            col = {"PASS": GREEN, "FAIL": RED, "WARN": YEL, "RUN": ACC}.get(st, MUT)
            cur = (self.i >= 0 and self.sequence[self.i][0] == k)
            if disabled:
                txt, col, mark = f"{title}  (atlandı)", "#3a4250", "○"
            else:
                txt = f"{mark}  {title}"
            tk.Label(bar, text=txt, anchor="w",
                     font=("Segoe UI", 12, "bold" if cur and not disabled else "normal"),
                     fg=(FG if cur and not disabled else col), bg=PANEL).pack(fill="x", padx=18, pady=4)
        right = tk.Frame(self.root, bg=BG)
        right.pack(side="right", fill="both", expand=True)

        # --- ust baslik çubuğu (logo + baslik + canli saat/makine) ---
        hdr = tk.Frame(right, bg=PANEL, height=58)
        hdr.pack(fill="x"); hdr.pack_propagate(False)
        if self.logo:
            tk.Label(hdr, image=self.logo, bg="white", padx=8, pady=4).pack(side="left", padx=12, pady=8)
        tk.Label(hdr, text="PC TEST ISTASYONU", font=("Segoe UI", 15, "bold"),
                 fg=FG, bg=PANEL).pack(side="left", padx=14)
        self.clock_lbl = tk.Label(hdr, text="", font=("Segoe UI", 12), fg=MUT, bg=PANEL)
        self.clock_lbl.pack(side="right", padx=16)
        tk.Frame(right, bg="#30363d", height=1).pack(fill="x")

        self.body = tk.Frame(right, bg=BG)
        self.body.pack(fill="both", expand=True)
        return self.body

    def _update_clock(self):
        try:
            if getattr(self, "clock_lbl", None) and self.clock_lbl.winfo_exists():
                self.clock_lbl.config(
                    text=time.strftime("%d.%m.%Y   %H:%M:%S") + "    |    " +
                         os.environ.get("COMPUTERNAME", ""))
        except Exception:
            pass
        self.root.after(1000, self._update_clock)

    def set_state(self, key, st):
        self.step_state[key] = st

    def record(self, cat, item, val, status):
        self.rows.append((cat, item, str(val), status))

    def advance(self):
        self.i += 1
        # işaretsiz adimlari atla; 'done' (ozet) her zaman çalışır
        while self.i < len(self.sequence):
            key = self.sequence[self.i][0]
            if key == "done" or self.enabled.get(key, tk.BooleanVar(value=True)).get():
                self.sequence[self.i][2]()
                return
            self.i += 1

    def add_risk(self, msg):
        """Sahada sorun cikarabilecek donanım -> uyari listesi + rapora WARN."""
        self.risks.append(msg)
        self.record("Saha Riski", "Uyarı", msg, "WARN")

    # ---------- giris ----------
    def _intro(self):
        b = self._shell()
        tk.Label(b, text="DOKUNMATIK PC  -  TAM TEST", font=("Segoe UI", 28, "bold"),
                 fg=ACC, bg=BG).pack(pady=(26, 4))
        tk.Label(b, text="Yapilacak testleri işaretleyin; sadece işaretliler sırayla çalışır.",
                 font=("Segoe UI", 14), fg=MUT, bg=BG, justify="center").pack(pady=4)

        # --- operatör / seri no (izlenebilirlik) ---
        meta = tk.Frame(b, bg=BG); meta.pack(pady=8)
        tk.Label(meta, text="Operatör:", font=("Segoe UI", 12), fg=MUT, bg=BG).grid(row=0, column=0, padx=6, pady=4, sticky="e")
        tk.Entry(meta, textvariable=self.op_var, width=20, font=("Segoe UI", 12), justify="center").grid(row=0, column=1, padx=6)
        tk.Label(meta, text="Seri No / İş emri:", font=("Segoe UI", 12), fg=MUT, bg=BG).grid(row=0, column=2, padx=6, pady=4, sticky="e")
        tk.Entry(meta, textvariable=self.sn_var, width=20, font=("Segoe UI", 12), justify="center").grid(row=0, column=3, padx=6)

        # --- test seçimi (tikler) ---
        sel = tk.Frame(b, bg=BG); sel.pack(pady=6)
        labels = {"screen": "Ekran (renk/dead-pixel)", "touch": "Dokunmatik çizim",
                  "grid": "Dokunmatik izgara", "inv": "Donanım envanteri",
                  "stress": "CPU/RAM stres", "ssd": "SSD hız",
                  "net": "Ağ / internet", "reset": "Reset / elektrik geçmişi"}
        keys = list(labels.keys())
        for idx, k in enumerate(keys):
            tk.Checkbutton(sel, text=labels[k], variable=self.enabled[k],
                           font=("Segoe UI", 13), fg=FG, bg=BG, selectcolor=PANEL,
                           activebackground=BG, activeforeground=FG, anchor="w", width=24
                           ).grid(row=idx // 2, column=idx % 2, sticky="w", padx=10, pady=2)
        bs = tk.Frame(b, bg=BG); bs.pack(pady=(2, 0))
        tk.Button(bs, text="Tümünü seç", font=("Segoe UI", 11), bg=PANEL, fg=FG, relief="flat",
                  command=lambda: [v.set(True) for v in self.enabled.values()]).pack(side="left", padx=4)
        tk.Button(bs, text="Hiçbiri", font=("Segoe UI", 11), bg=PANEL, fg=FG, relief="flat",
                  command=lambda: [v.set(False) for v in self.enabled.values()]).pack(side="left", padx=4)

        # --- stres / burn-in süresi seçimi ---
        tk.Label(b, text="CPU / RAM stres (burn-in) süresi:", font=("Segoe UI", 15, "bold"),
                 fg=FG, bg=BG).pack(pady=(16, 6))
        row = tk.Frame(b, bg=BG); row.pack()
        for val, lab in [("1", "1 dk"), ("5", "5 dk"), ("30", "30 dk"), ("60", "1 saat"), ("120", "2 saat")]:
            tk.Button(row, text=lab, font=("Segoe UI", 13), bg=PANEL, fg=FG, relief="flat",
                      width=7, padx=4, pady=8,
                      command=lambda v=val: self.minutes_var.set(v)).pack(side="left", padx=5)
        custom = tk.Frame(b, bg=BG); custom.pack(pady=12)
        tk.Label(custom, text="Özel: ", font=("Segoe UI", 13), fg=MUT, bg=BG).pack(side="left")
        tk.Entry(custom, textvariable=self.minutes_var, width=6, font=("Segoe UI", 14),
                 justify="center").pack(side="left")
        tk.Label(custom, text=" dakika", font=("Segoe UI", 13), fg=MUT, bg=BG).pack(side="left")

        tk.Button(b, text="TESTE BASLA  ▶", font=("Segoe UI", 20, "bold"),
                  bg=GREEN, fg="#06210f", relief="flat", padx=40, pady=14,
                  command=self._start).pack(pady=18)
        tk.Label(b, text=f"Endutek PC Test  v{APP_VERSION}   •   Uzun testlerde sıcaklık 15 sn'de bir CSV'ye loglanir   •   acil çıkış: F10",
                 font=("Segoe UI", 10), fg=MUT, bg=BG).pack(side="bottom", pady=12)

    def _start(self):
        try:
            mins = max(1, int(float(self.minutes_var.get().replace(",", "."))))
        except Exception:
            mins = 1
        self.stress_sec = mins * 60
        self.advance()

    # ---------- ortak: otomatik adim cercevesi ----------
    def auto_panel(self, key, title, determinate=False):
        self.set_state(key, "RUN")
        b = self._shell()
        tk.Label(b, text=title, font=("Segoe UI", 22, "bold"), fg=FG, bg=BG).pack(pady=(36, 8), anchor="w", padx=40)
        self.status = tk.Label(b, text="Çalışıyor...", font=("Segoe UI", 14), fg=ACC, bg=BG)
        self.status.pack(anchor="w", padx=40)
        # ilerleme çubuğu (ttk)
        self.pbar = ttk.Progressbar(b, length=560, mode=("determinate" if determinate else "indeterminate"),
                                    style="Blue.Horizontal.TProgressbar")
        self.pbar.pack(anchor="w", padx=40, pady=14)
        if determinate:
            self.pbar["maximum"] = 100
        else:
            self.pbar.start(14)
        self.detail = tk.Label(b, text="", font=("Consolas", 13), fg=FG, bg=BG, justify="left")
        self.detail.pack(anchor="w", padx=40, pady=6)
        self.progress = tk.Label(b, text="", font=("Segoe UI", 13), fg=MUT, bg=BG)
        self.progress.pack(anchor="w", padx=40)
        return b

    def run_async(self, work, done):
        def runner():
            try:
                r = work()
            except Exception as e:
                r = e
            self.root.after(0, lambda: done(r))
        threading.Thread(target=runner, daemon=True).start()

    def finish_auto(self, key, status, lines):
        self.set_state(key, status)
        try:
            self.pbar.stop()
            self.pbar["mode"] = "determinate"
            self.pbar["maximum"] = 100
            self.pbar["value"] = 100
            self.pbar["style"] = "Green.Horizontal.TProgressbar" if status != "FAIL" else "Blue.Horizontal.TProgressbar"
        except Exception:
            pass
        col = {"PASS": GREEN, "FAIL": RED, "WARN": YEL}.get(status, FG)
        self.status.config(text=f"SONUC: {status}", fg=col)
        self.detail.config(text="\n".join(lines))
        self.progress.config(text="Sonraki adıma geçiliyor...")
        # FAIL'de operatör gorsun: 5 sn, aksi halde 2.5 sn sonra otomatik ilerle
        self.root.after(5000 if status == "FAIL" else 2500, self.advance)

    # ---------- derecelendirme (her donanım icin) ----------
    def set_grade(self, comp, score):
        self.grades[comp] = max(0, min(3, int(score)))

    def _set_pbar(self, v):
        try:
            self.pbar["value"] = v
        except Exception:
            pass

    def overall_grade(self):
        """Genel not = en zayif bilesen (zincir en zayif halkasi kadar saglam)."""
        return min(self.grades.values()) if self.grades else None

    # ===================== 1) EKRAN =====================
    def step_screen(self):
        self.set_state("screen", "RUN")
        for w in self.root.winfo_children():
            w.destroy()
        cv = tk.Canvas(self.root, highlightthickness=0)
        cv.pack(fill="both", expand=True)
        self._ci = 0

        def show(i):
            name, color = PALETTE[i]
            cv.configure(bg=color)
            cv.delete("all")
            fg = "#000" if color in ("#FFFFFF", "#808080") else "#888"
            cv.create_text(self.sw / 2, 40, fill=fg, font=("Segoe UI", 16),
                           text=f"{name}  ({i + 1}/{len(PALETTE)})  -  ekrana dokun: sonraki renk")

        def nxt(_=None):
            self._ci += 1
            if self._ci >= len(PALETTE):
                ask()
            else:
                show(self._ci)

        def ask():
            cv.configure(bg=BG)
            cv.delete("all")
            cv.create_text(self.sw / 2, self.sh / 2 - 80, fill=FG, font=("Segoe UI", 26, "bold"),
                           text="Ekranda ölü piksel / renk / parlaklık sorunu var miydi?")
            tk.Button(self.root, text="GEÇTİ ✓", font=("Segoe UI", 20, "bold"),
                      bg=GREEN, fg="#06210f", relief="flat", padx=30, pady=14,
                      command=lambda: done("PASS")).place(relx=0.38, rely=0.55, anchor="center")
            tk.Button(self.root, text="HATALI ✗", font=("Segoe UI", 20, "bold"),
                      bg=RED, fg="#2a0a0a", relief="flat", padx=30, pady=14,
                      command=lambda: done("FAIL")).place(relx=0.62, rely=0.55, anchor="center")

        def done(st):
            self.set_state("screen", st)
            self.record("Ekran", "Renk/dead-pixel", "operatör: " + st, st)
            self.set_grade("Ekran", 3 if st == "PASS" else 0)
            self.advance()

        cv.bind("<Button-1>", nxt)
        show(0)

    # ===================== 2) DOKUNMATIK CIZIM =====================
    def step_touch(self):
        self.set_state("touch", "RUN")
        for w in self.root.winfo_children():
            w.destroy()
        cv = tk.Canvas(self.root, bg="black", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        last = {}

        def down(e): last["p"] = (e.x, e.y)

        def move(e):
            p = last.get("p")
            if p:
                cv.create_line(p[0], p[1], e.x, e.y, fill="#00ff66", width=5,
                               capstyle="round", smooth=True)
            last["p"] = (e.x, e.y)

        def up(_): last.pop("p", None)

        cv.bind("<Button-1>", down); cv.bind("<B1-Motion>", move); cv.bind("<ButtonRelease-1>", up)
        cv.create_text(self.sw / 2, 30, fill="#888", font=("Segoe UI", 15),
                       text="Parmaginla çizim yap - kesintisiz iz cikmali")

        def done(st):
            self.set_state("touch", st)
            self.record("Dokunmatik", "Çizim", "operatör: " + st, st)
            self.set_grade("Dokunmatik", 3 if st == "PASS" else 0)
            self.advance()

        tk.Button(self.root, text="GEÇTİ ✓", font=("Segoe UI", 16, "bold"), bg=GREEN, fg="#06210f",
                  relief="flat", padx=18, pady=8, command=lambda: done("PASS")).place(x=20, y=20)
        tk.Button(self.root, text="HATALI ✗", font=("Segoe UI", 16, "bold"), bg=RED, fg="#2a0a0a",
                  relief="flat", padx=18, pady=8, command=lambda: done("FAIL")).place(x=160, y=20)
        tk.Button(self.root, text="Temizle", font=("Segoe UI", 14), bg=PANEL, fg=FG,
                  relief="flat", padx=14, pady=8, command=lambda: cv.delete("all")).place(x=320, y=20)

    # ===================== 3) DOKUNMATIK IZGARA =====================
    def step_grid(self):
        self.set_state("grid", "RUN")
        for w in self.root.winfo_children():
            w.destroy()
        cv = tk.Canvas(self.root, bg="#111", highlightthickness=0)
        cv.pack(fill="both", expand=True)
        cols, rows = 8, 5
        cw, ch = self.sw / cols, self.sh / ch_safe(rows)
        cells, touched = {}, set()
        for r in range(rows):
            for c in range(cols):
                x0, y0 = c * cw, r * ch
                cells[(c, r)] = cv.create_rectangle(x0 + 2, y0 + 2, x0 + cw - 2, y0 + ch - 2,
                                                    fill="#26323d", outline="#3a4a5a")
        hint = cv.create_text(self.sw / 2, self.sh / 2, fill="#566",
                              font=("Segoe UI", 22), text="Her kareye dokun")

        def done(st):
            self.set_state("grid", st)
            self.record("Dokunmatik", "Izgara kapsama", f"{len(touched)}/{cols*rows} hücre", st)
            self.set_grade("Dokunmatik", min(self.grades.get("Dokunmatik", 3), 3 if st == "PASS" else 0))
            self.advance()

        def touch(e):
            c, r = int(e.x // cw), int(e.y // ch)
            if (c, r) in cells and (c, r) not in touched:
                touched.add((c, r))
                cv.itemconfig(cells[(c, r)], fill="#00aa55")
                if len(touched) == cols * rows:
                    cv.itemconfig(hint, text="TÜM HÜCRELER OK", fill=GREEN)
                    self.root.after(700, lambda: done("PASS"))

        cv.bind("<Button-1>", touch); cv.bind("<B1-Motion>", touch)
        tk.Button(self.root, text="ATLA / HATALI", font=("Segoe UI", 14), bg=RED, fg="#2a0a0a",
                  relief="flat", padx=14, pady=8, command=lambda: done("FAIL")).place(x=20, y=20)

    # ===================== 4) ENVANTER + SAGLIK =====================
    def step_inventory(self):
        self.auto_panel("inv", "4. Donanım Envanteri + Sağlık (cipset/USB/sensör)")

        def work():
            inv = ps_json(PS_INVENTORY)
            health = ps_json(PS_HEALTH, timeout=60)
            return inv, health

        self.run_async(work, self._after_inv)

    def _after_inv(self, res):
        d, health = res if isinstance(res, tuple) and len(res) == 2 else (res, None)
        if not isinstance(d, dict):
            self.record("Envanter", "WMI", "okunamadı", "WARN")
            self.finish_auto("inv", "WARN", ["Donanım bilgisi okunamadı (Yonetici?)."])
            return
        self.inv = d
        self.health = health or {}
        disks = d.get("disks") or []
        if isinstance(disks, dict):
            disks = [disks]
        lines = [
            f"Anakart : {d.get('board','')}",
            f"Seri No : {d.get('serial','')}",
            f"CPU     : {d.get('cpu','')}  ({d.get('cores')}c/{d.get('threads')}t)",
            f"RAM     : {d.get('ramgb')} GB",
            f"GPU     : {d.get('gpu','')}",
            f"Çözünürlük: {d.get('res','')}",
        ]
        status = "PASS"
        ram = d.get("ramgb") or 0
        self.record("Envanter", "Anakart", d.get("board", ""), "INFO")
        self.record("Envanter", "Seri No", d.get("serial", ""), "INFO")
        self.record("Envanter", "CPU", d.get("cpu", ""), "INFO")
        if ram >= EXPECTED["min_ram_gb"]:
            self.record("Envanter", "RAM", f"{ram} GB", "PASS")
        else:
            self.record("Envanter", "RAM", f"{ram} GB (< {EXPECTED['min_ram_gb']})", "FAIL"); status = "FAIL"
        dh = 3
        if disks:
            self.sys_media = disks[0].get("media", ""); self.sys_bus = disks[0].get("bus", "")
        for dk in disks:
            nm = dk.get("name", "")
            h = dk.get("health", "")
            st = "PASS" if h == "Healthy" else "FAIL"
            if st == "FAIL":
                status = "FAIL"
            ttxt = f", {dk.get('temp')}C" if dk.get("temp") else ""
            lines.append(f"Disk    : {nm} {dk.get('gb')}GB {dk.get('media','')} [{h}{ttxt}]")
            self.record("Disk", nm, f"{dk.get('gb')}GB / {h}", st)
            # --- disk SAGLIK derecesi (karakteristige gore) ---
            _w, _t, _ph = dk.get("wear"), dk.get("temp"), dk.get("poh")
            if h != "Healthy":
                g = 0
            elif dk.get("readErr") or dk.get("writeErr"):
                g = 1
            elif isinstance(_w, (int, float)) and _w >= 10:
                g = 1
            elif isinstance(_t, (int, float)) and _t >= 60:
                g = 1
            elif isinstance(_ph, (int, float)) and _ph >= 100:
                g = 2
            else:
                g = 3
            dh = min(dh, g)
            # --- saha riski: SMART karakteristikleri ---
            if h and h != "Healthy":
                self.add_risk(f"Disk '{nm}' sağlık durumu '{h}' — sahada arızalanabilir, DEĞİŞTİRİN.")
            wear = dk.get("wear")
            if isinstance(wear, (int, float)) and wear >= 10:
                self.add_risk(f"SSD '{nm}' asinma %{wear:0.0f} — omru azaliyor, kritik cihaza takmayin.")
            temp = dk.get("temp")
            if isinstance(temp, (int, float)) and temp >= 60:
                self.add_risk(f"Disk '{nm}' sıcakligi {temp}C — yuksek; sahada ısınma/arızaya yatkin.")
            if dk.get("readErr"):
                self.add_risk(f"Disk '{nm}' okuma hatasi sayaci {dk.get('readErr')} — veri kaybi riski.")
            if dk.get("writeErr"):
                self.add_risk(f"Disk '{nm}' yazma hatasi sayaci {dk.get('writeErr')} — veri kaybi riski.")
            poh = dk.get("poh")
            if isinstance(poh, (int, float)) and poh >= 100:
                self.add_risk(f"Disk '{nm}' çalışma saati {poh}h — SIFIR cihazda yuksek (kullanilmis disk olabilir).")
        # --- BIOS + CMOS/BIOS pil (saat sıfırlanmasi) ---
        biosv = d.get("bios", "")
        if biosv:
            lines.append(f"BIOS    : {biosv}  ({d.get('bios_year') or '?'})")
            self.record("BIOS", "Sürüm", biosv, "INFO")
        if d.get("os_install"):
            lines.append(f"Windows kurulum: {d.get('os_install')}")
            self.record("Envanter", "Windows kurulum", d.get("os_install"), "INFO")
        sysyear = d.get("sysyear") or 0
        biosyear = d.get("bios_year") or 0
        # CMOS pili bitince saat sifirlanir -> sistem yili BIOS yilindan eski/mantıksız olur
        if sysyear and (sysyear < 2020 or (biosyear and sysyear < biosyear)):
            self.record("BIOS", "CMOS pil", f"saat sapmis (yil {sysyear})", "WARN")
            self.add_risk(f"CMOS/BIOS pili (anakart düğme pil) BITMIS olabilir — sistem saati mantıksız "
                          f"(yil {sysyear}); saat sıfırlanıyor, sahada tarih/lisans/sertifika sorunlari cikar. Pili (CR2032) değiştirin.")
        else:
            self.record("BIOS", "CMOS pil", "saat tutarlı", "PASS")
        # sistem diski boş alan riski
        free = d.get("sysfree_gb")
        if isinstance(free, (int, float)) and free < 15:
            self.add_risk(f"Sistem diski boş alani düşük ({free} GB) — sahada güncelleme/log dolma sorunu.")
        # --- derece: Disk (sağlık). RAM derecesi stres adiminda (yaz/oku sagligi) verilir.
        #     Tek/cift kanal veya kapasiteye gore RAM DERECELENDIRMESI YAPILMAZ (karakteristik).
        self.set_grade("Disk", dh)
        self.record("Envanter", "GPU", d.get("gpu", ""), "INFO")

        # --- CIPSET / USB / VOLTAJ / ISI sağlık ---
        h = self.health
        probs = h.get("problems") or []
        if isinstance(probs, dict):
            probs = [probs]
        # PS/2 hayalet aygıtlar ve "aygıt yok" (kod 24) ZARARSIZ -> sayma.
        # Kod 28 = sürücü yuklu değil -> minor. Digerleri (10/43/1..) = gercek arıza.
        serious, minor = [], []
        for p in probs:
            nm = str(p.get("name", "")); code = p.get("code")
            if "PS/2" in nm or code == 24:
                continue
            if code == 28:
                minor.append((nm, code))
            else:
                serious.append((nm, code))
        if serious:
            self.set_grade("Çipset", 0 if len(serious) >= 2 else 1)
            self.record("Çipset", "Arızalı aygıt", f"{len(serious)} adet", "WARN")
            lines.append(f"Çipset: {len(serious)} arızalı aygıt:")
            for nm, code in serious[:5]:
                lines.append(f"   - {nm} (kod {code})")
                self.add_risk(f"Arızalı aygıt: {nm} (kod {code}) — cipset/donanım sorunu, kontrol edin.")
            if status == "PASS":
                status = "WARN"
        elif minor:
            self.set_grade("Çipset", 2)
            self.record("Çipset", "Sürücü eksik", f"{len(minor)} aygıt", "INFO")
            lines.append(f"Çipset: aygıtlar sağlıklı; {len(minor)} aygıtın sürücüsu eksik (minor):")
            for nm, code in minor[:5]:
                lines.append(f"   - {nm}: sürücü yüklenmemis (kod {code})")
        else:
            self.set_grade("Çipset", 3)
            self.record("Çipset", "Cihaz/sürücü", "tüm cihazlar sağlıklı", "PASS")
            lines.append("Çipset/sürücü: tüm cihazlar sağlıklı")
        usbc = h.get("usb_ctrl") or 0
        usbp = h.get("usb_prob") or 0
        if usbc > 0 and usbp == 0:
            self.set_grade("USB", 3)
        elif usbp > 0:
            self.set_grade("USB", 1)
            self.add_risk(f"{usbp} USB aygıtında sorun (sürücü/bağlantı) var.")
            if status == "PASS":
                status = "WARN"
        else:
            self.set_grade("USB", 2)
        self.record("USB", "Denetleyici/sorun", f"{usbc} denetleyici / {usbp} sorun", "PASS" if usbp == 0 else "WARN")
        lines.append(f"USB: {usbc} denetleyici, {usbp} sorunlu aygıt")
        volt = h.get("volt")
        if volt:
            lines.append(f"CPU voltaj: {volt} V")
            self.record("Sensör", "CPU voltaj", f"{volt} V", "INFO")
            if volt < 0.6 or volt > 1.6:
                self.add_risk(f"CPU voltaji {volt}V — beklenen aralik (0.6-1.6V) disinda.")
        else:
            lines.append("CPU voltaj: standart WMI'dan okunamadı (anakart raylari icin özel sürücü gerekir)")
        zones = h.get("zones") or []
        if isinstance(zones, (int, float)):
            zones = [zones]
        if zones:
            zt = ", ".join(f"{z}C" for z in zones)
            lines.append(f"Isı bölgeleri: {zt}")
            self.record("Sensör", "Isı bölgeleri", zt, "INFO")

        self.finish_auto("inv", status, lines)

    # ===================== 5) STRES =====================
    def step_stress(self):
        dur = self.stress_sec
        mm, ss = divmod(dur, 60)
        self.auto_panel("stress", f"5. CPU / RAM Stres  ({mm} dk {ss} sn)", determinate=True)
        ncpu = os.cpu_count() or 2
        self.status.config(text=f"{ncpu} çekirdek yükleniyor...")
        st0 = get_loadstat()
        temp_before = st0.get("temp")
        batt_present = bool(st0.get("batt_present"))
        batt_idle = st0.get("batt")          # yük oncesi pil durumu

        # uzun test (>=5 dk) ise CSV log
        csv_path = None
        if dur >= 300:
            comp = (self.inv or {}).get("computer", os.environ.get("COMPUTERNAME", "PC"))
            csv_path = os.path.join(base_dir(), f"burnin_{comp}_{time.strftime('%Y%m%d_%H%M%S')}.csv")
        self.stress_csv = csv_path

        def waiter():
            # 1) yük YOKKEN tek-çekirdek performans indeksi
            self.root.after(0, lambda: self.status.config(text="Performans ölçümu (tek çekirdek)..."))
            perf = cpu_bench(1.5)
            # 2) tüm çekirdeklere yükü bindir
            procs = [mp.Process(target=_cpu_worker, args=(dur,)) for _ in range(ncpu)]
            for p in procs:
                p.start()
            self.root.after(0, lambda: self.status.config(text=f"{ncpu} çekirdek yükleniyor..."))
            t0 = time.time()
            peak = temp_before or 0.0
            minclock = st0.get("clock") or 0
            maxclock = st0.get("maxclock") or 0
            batt_load = []                    # yük altında görülen pil durumlari
            next_s = 0.0
            f = None
            try:
                if csv_path:
                    f = open(csv_path, "w", encoding="utf-8")
                    f.write("saat,geçen_dk,cpu_temp_C,cpu_mhz\n")
            except Exception:
                f = None
            while any(p.is_alive() for p in procs):
                el = time.time() - t0
                if el >= next_s:                      # 15 sn'de bir sıcaklık+saat+pil ornekle
                    s = get_loadstat()
                    t = s.get("temp")
                    if t and t > peak:
                        peak = t
                    ck = s.get("clock") or 0
                    if ck and (minclock == 0 or ck < minclock):
                        minclock = ck
                    if s.get("maxclock"):
                        maxclock = s.get("maxclock")
                    if s.get("batt") is not None:
                        batt_load.append(s.get("batt"))
                    if f:
                        f.write(f"{time.strftime('%H:%M:%S')},{el/60:.1f},{t if t else 'NA'},{ck}\n"); f.flush()
                    next_s = el + 15
                rem = max(0, dur - el)
                pct = min(100, el / dur * 100)
                self.root.after(0, lambda e=el, r=rem, pk=peak, pc=pct: (
                    self.progress.config(
                        text=f"geçen {e/60:0.1f} dk  /  kalan {r/60:0.1f} dk    peak sıcaklık: "
                             f"{('%.0f C' % pk) if pk else 'N/A'}"),
                    self._set_pbar(pc)))
                time.sleep(0.5)
            for p in procs:
                p.join()
            if f:
                f.close()
            self.root.after(0, lambda: self.progress.config(text="RAM yaz/oku doğrulaması..."))
            ram_ok = ram_verify(EXPECTED["ram_test_mb"])
            sa = get_loadstat()
            temp_after = sa.get("temp")
            if temp_after and temp_after > peak:
                peak = temp_after
            self.stress_peak = peak if peak else None
            extra = {"minclock": minclock, "maxclock": maxclock, "batt_present": batt_present,
                     "batt_idle": batt_idle, "batt_load": batt_load, "perf": perf}
            self.root.after(0, lambda: self._after_stress(temp_before, temp_after, peak, ram_ok, extra))

        threading.Thread(target=waiter, daemon=True).start()

    def _after_stress(self, tb, ta, peak, ram_ok, extra=None):
        extra = extra or {}
        lines, status = [], "PASS"
        mm, ss = divmod(self.stress_sec, 60)
        lines.append(f"CPU yükü tamamlandi ({os.cpu_count()} çekirdek, {mm} dk {ss} sn).")
        self.record("Stres", "CPU yük süresi", f"{mm}dk {ss}sn", "PASS")
        perf = extra.get("perf")
        if perf:
            lines.append(f"Performans (tek çekirdek): {perf:,} op/s")
            self.record("Performans", "Tek çekirdek", f"{perf:,} op/s", "INFO")
        if ram_ok:
            lines.append(f"RAM doğrulama: OK ({EXPECTED['ram_test_mb']} MB)")
            self.record("Stres", "RAM doğrulama", f"{EXPECTED['ram_test_mb']}MB OK", "PASS")
        else:
            lines.append("RAM doğrulama: HATA!")
            self.record("Stres", "RAM doğrulama", "HATA", "FAIL"); status = "FAIL"
        if peak:
            lines.append(f"CPU sıcaklık: {tb if tb else '?'}C -> peak {peak:0.0f}C (limit {EXPECTED['max_cpu_temp']})")
            if peak > EXPECTED["max_cpu_temp"]:
                self.record("Stres", "CPU peak sıcaklık", f"{peak:0.0f}C", "FAIL"); status = "FAIL"
                self.add_risk(f"CPU yük altında {peak:0.0f}C — limit aşıldı; soğutma yetersiz, sahada throttle/kapanma riski.")
            else:
                self.record("Stres", "CPU peak sıcaklık", f"{peak:0.0f}C", "PASS")
                if peak >= EXPECTED["max_cpu_temp"] - 10:
                    self.add_risk(f"CPU peak {peak:0.0f}C — limite yakın ({EXPECTED['max_cpu_temp']}C); sıcak ortamda riskli, soğutmayı kontrol edin.")
        else:
            lines.append("CPU sıcaklık: WMI'dan okunamadı (bazi anakartlarda normal).")
            self.record("Stres", "CPU sıcaklık", "N/A", "INFO")
        if self.stress_csv:
            lines.append(f"Sıcaklık logu: {os.path.basename(self.stress_csv)}")
            self.record("Stres", "Burn-in log", os.path.basename(self.stress_csv), "INFO")
        # --- dereceler: CPU (sıcaklık marji / throttle) + RAM (verify) ---
        lim = EXPECTED["max_cpu_temp"]
        if peak:
            if peak > lim:
                cpu_g = 0                      # aştı: soğutma yetersiz
            elif peak >= lim - 10:
                cpu_g = 1                      # limite cok yakın
            elif peak >= lim - 25:
                cpu_g = 2                      # makul marj
            else:
                cpu_g = 3                      # bol marj, kararli (eski CPU icin SÜPER)
        else:
            cpu_g = 2                          # sıcaklık okunamadı -> cezalandirma, notr
        self.set_grade("CPU", cpu_g)
        self.set_grade("RAM", 0 if not ram_ok else 3)   # sadece sağlık (yaz/oku); kapasite/kanal değil

        # --- throttle tespiti (saat yük altında düştü mu) ---
        minc = extra.get("minclock") or 0
        maxc = extra.get("maxclock") or 0
        throttled = bool(maxc and minc and minc < 0.80 * maxc)
        if throttled:
            lines.append(f"CPU saati yük altında düştü: {minc}/{maxc} MHz (throttle)")
            self.record("Stres", "CPU throttle", f"{minc}/{maxc} MHz", "WARN")

        # --- SOGUTMA değerlendirmesi (sıcaklık + throttle) ---
        if peak:
            if peak > lim:
                cool_g, cool_t = 0, "YETERSİZ"
                self.add_risk("Soğutma YETERSİZ — CPU yük altında limiti aştı; fan/termal macun/havalandırma kontrol edin.")
            elif peak >= lim - 10:
                cool_g, cool_t = 1, "SINIRDA"
                self.add_risk(f"Soğutma SINIRDA — peak {peak:0.0f}C limite yakın; sıcak ortamda yetersiz kalabilir.")
            elif peak >= lim - 25:
                cool_g, cool_t = 2, "İYİ"
            else:
                cool_g, cool_t = 3, "COK İYİ"
            if throttled and peak >= lim - 15:        # sıcaklıktan throttle -> soğutma sucu
                cool_g = min(cool_g, 1)
            self.set_grade("Soğutma", cool_g)
            lines.append(f"Soğutma: {cool_t}")
            self.record("Stres", "Soğutma", cool_t, "PASS" if cool_g >= 2 else "WARN")
        else:
            lines.append("Soğutma: sıcaklık okunamadı -> değerlendirilemedi")

        # --- ADAPTOR / GUC değerlendirmesi ---
        bp = extra.get("batt_present")
        bi = extra.get("batt_idle")
        bl = extra.get("batt_load") or []
        if bp:
            if bi == 1:                               # idle'da boşalıyor -> priz takili değil
                self.record("Stres", "Adaptör", "priz takili değil", "WARN")
                lines.append("Adaptör: PRIZ TAKILI DEGIL — test prizden yapılmalı, adaptör değerlendirilemedi.")
                self.add_risk("Adaptör testi icin cihaz prize takili olmali (pilden çalışıyordu).")
            elif 1 in bl:                             # fisliyken yük altında bosaldi -> zayif adaptör
                self.set_grade("Adaptör", 0)
                self.record("Stres", "Adaptör", "ZAYIF (yukte pil boşalıyor)", "FAIL")
                lines.append("Adaptör: ZAYIF — fise takiliyken yük altında pil boşalıyor, adaptör yetersiz.")
                self.add_risk("Adaptör yükü karşılayamıyor (yük altında pil boşalıyor) — daha güçlu adaptör gerekli.")
                status = "WARN" if status == "PASS" else status
            else:
                self.set_grade("Adaptör", 3)
                self.record("Stres", "Adaptör", "İYİ", "PASS")
                lines.append("Adaptör: İYİ (yük altında güçu karşıladı).")
        else:
            # pilsiz DC cihaz: sıcaklık düşükken throttle -> güç/adaptör siniri suphesi
            if throttled and peak and peak < lim - 25:
                self.set_grade("Adaptör", 1)
                self.record("Stres", "Adaptör/Güç", "sınırlı olabilir", "WARN")
                lines.append("Adaptör/Güç: throttle var ama sıcaklık düşük -> güç/adaptör sınırlı olabilir.")
                self.add_risk("Yük altinda throttle + düşük sıcaklık — güç/adaptör sınırlaması olabilir, adaptöru kontrol edin.")
            else:
                self.set_grade("Adaptör", 3)
                self.record("Stres", "Adaptör/Güç", "yeterli (DC)", "PASS")
                lines.append("Adaptör/Güç: yeterli (yük altında güç sınırlaması görülmedi).")

        self.finish_auto("stress", status, lines)

    # ===================== 6) SSD / DISK SAGLIK + HIZ =====================
    def step_ssd(self):
        self.auto_panel("ssd", "6. SSD / Disk  -  sağlık + hız + bütünlük")
        self.status.config(text=f"{EXPECTED['ssd_test_mb']} MB yaz/oku/doğrula + dosya sistemi taramasi...")

        def work():
            spd = ssd_speed(EXPECTED["ssd_test_mb"])
            scan = ps_json(PS_DISKSCAN, timeout=90)
            return spd, scan

        self.run_async(work, self._after_ssd)

    def _after_ssd(self, res):
        spd, scan = (res if isinstance(res, tuple) and len(res) == 2 else (None, None))
        if not (isinstance(spd, tuple) and len(spd) == 3):
            self.record("SSD", "Hız", "hata", "WARN")
            self.set_grade("Disk", min(self.grades.get("Disk", 3), 1))
            self.finish_auto("ssd", "WARN", ["SSD testi yapılamadı."])
            return
        w, r, integ = spd
        status = "PASS"
        ws = "PASS" if w >= EXPECTED["min_ssd_write"] else "WARN"
        rs = "PASS" if r >= EXPECTED["min_ssd_read"] else "WARN"
        if "WARN" in (ws, rs):
            status = "WARN"
        self.record("SSD", "Yazma", f"{w} MB/s", ws)
        self.record("SSD", "Okuma", f"{r} MB/s", rs)
        lines = [f"Yazma: {w} MB/s   Okuma: {r} MB/s"]

        # --- veri bütünlüğü (elektrik kesintisi/bozuk blok yakalar) ---
        if integ:
            self.record("SSD", "Veri bütünlüğü", "OK", "PASS")
            lines.append("Veri bütünlüğü: OK (yazilan = okunan)")
        else:
            self.record("SSD", "Veri bütünlüğü", "HATA", "FAIL")
            lines.append("Veri bütünlüğü: HATA! bozuk/zayif blok")
            status = "FAIL"
            self.add_risk("SSD veri bütünlüğü BOZUK — yazilan veri geri okunamadı; disk arızalı/bozuk blok, DEĞİŞTİRİN.")

        # --- dosya sistemi dirty + tarama ---
        dirty = (scan or {}).get("dirty", "NA")
        scn = (scan or {}).get("scan", "NA")
        if dirty == "KIRLI":
            lines.append("Dosya sistemi: KIRLI bit set (düzgün kapanmamis)")
            self.record("Disk", "Dosya sistemi", "KIRLI bit", "WARN")
            self.add_risk("Dosya sistemi 'kirli' işaretli — son kapanma düzgün değildi (elektrik?); chkdsk önerilir.")
            if status == "PASS":
                status = "WARN"
        if scn and scn not in ("NoErrorsFound", "NA", ""):
            lines.append(f"Disk taramasi: {scn}")
            self.record("Disk", "Tarama", scn, "WARN")
            self.add_risk(f"Disk taramasi '{scn}' — dosya sistemi bozulmasi; chkdsk/onarim gerekli (elektrik kesintisi hasari olabilir).")
            if status == "PASS":
                status = "WARN"

        # --- hız derecesi: MEDYA tipine gore adil (HDD/SATA-SSD/NVMe) ---
        bw, br = disk_speed_baseline(self.sys_bus, self.sys_media)
        ratio = min(w / bw if bw else 1, r / br if br else 1)
        if ratio >= 0.9:
            sg = 3
        elif ratio >= 0.6:
            sg = 2
        elif ratio >= 0.4:
            sg = 1
        else:
            sg = 0
        # bütünlük/dosya sistemi sorunu varsa disk notu kotulesir
        if not integ:
            sg = 0
        elif dirty == "KIRLI" or (scn and scn not in ("NoErrorsFound", "NA", "")):
            sg = min(sg, 1)
        self.set_grade("Disk", min(self.grades.get("Disk", 3), sg))
        lines.append(f"Beklenen ({self.sys_bus or '?'}): ~{bw}/{br} MB/s")
        self.finish_auto("ssd", status, lines)

    # ===================== 7) AG =====================
    def step_network(self):
        self.auto_panel("net", "7. Ağ / İnternet")
        self.run_async(lambda: ps_json(PS_NETWORK), self._after_net)

    def _after_net(self, d):
        if not isinstance(d, dict):
            self.record("Ağ", "Adaptör", "okunamadı", "WARN")
            self.finish_auto("net", "WARN", ["Ağ bilgisi okunamadı."])
            return
        ad = d.get("adapters") or []
        if isinstance(ad, dict):
            ad = [ad]
        lines, status, up_any = [], "PASS", False
        for a in ad:
            st = a.get("status", "")
            lines.append(f"{a.get('name','')}: {st} ({a.get('mbps',0)} Mbps)")
            if st == "Up":
                up_any = True
            self.record("Ağ", a.get("name", ""), f"{st} / {a.get('mbps',0)}Mbps",
                        "PASS" if st == "Up" else "INFO")
        ping = d.get("pingms")
        if ping is not None:
            lines.append(f"İnternet ping: {ping} ms")
            self.record("Ağ", "İnternet", f"{ping} ms", "PASS")
        else:
            lines.append("İnternet: yok")
            self.record("Ağ", "İnternet", "yok", "WARN")
            if status == "PASS":
                status = "WARN"
        if not up_any:
            status = "WARN"
        # --- ag derecesi: link + internet ---
        eth_up = any(a.get("status") == "Up" and "Ethernet" in a.get("name", "") for a in ad)
        if not up_any:
            ng = 0
        elif eth_up and ping is not None:
            ng = 3
        elif up_any and ping is not None:
            ng = 2
        else:
            ng = 1
        self.set_grade("Ag", ng)
        self.finish_auto("net", status, lines)

    # ===================== 8) RESET / ELEKTRIK GECMISI =====================
    def step_reset(self):
        self.auto_panel("reset", "8. Reset / Elektrik + USB Güç/Arıza Geçmişi (son 90 gun)")

        def work():
            hist = ps_json(PS_RESET_HIST)
            usb = ps_json(PS_USBEVENTS, timeout=90)
            crit = ps_json(PS_CRITICAL, timeout=120)
            return hist, usb, crit

        self.run_async(work, self._after_reset)

    def _after_reset(self, res):
        if isinstance(res, tuple) and len(res) == 3:
            data, usb, crit = res
        elif isinstance(res, tuple) and len(res) == 2:
            data, usb, crit = res[0], res[1], None
        else:
            data, usb, crit = res, None, None
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            data = []
        self.reset_events = data
        # --- USB güç dalgalanması / arıza olaylari ---
        usb = usb or {}
        surge = usb.get("surge") or []
        fault = usb.get("fault") or []
        if isinstance(surge, dict):
            surge = [surge]
        if isinstance(fault, dict):
            fault = [fault]
        self.usb_events = {"surge": surge, "fault": fault}
        c = lambda t: sum(1 for e in data if e.get("type") == t)
        boot, clean, soft = c("ACILIS"), c("TEMIZ"), c("SOFT")
        unexp = count_unexpected(data)          # 41+6008 ayni olay -> teklestirilir
        self.reset_unexp = unexp
        self.record("Reset", "Beklenmedik (90g)", unexp, "WARN" if unexp else "PASS")
        self.record("Reset", "Soft-reset (90g)", soft, "INFO")
        self.record("Reset", "Temiz kapanma (90g)", clean, "INFO")
        lines = [f"Açılış: {boot}    Temiz: {clean}    Soft-reset: {soft}    BEKLENMEDIK: {unexp}",
                 "(BEKLENMEDIK = elektrik kesintisi veya manuel/hard-reset)", ""]
        for e in reversed(data[-8:]):   # en yeni ustte
            lines.append(f"{e.get('time','')}  [{e.get('type',''):<11}] {e.get('detail','')[:50]}")
        # --- USB güç/arıza olaylari ---
        ns, nf = len(surge), len(fault)
        lines.append("")
        lines.append(f"USB güç dalgalanması/aşırı akim: {ns}   |   USB arıza/tanınmayan: {nf}")
        self.record("USB olay", "Güç dalgalanması (90g)", ns, "WARN" if ns else "PASS")
        self.record("USB olay", "Arıza/tanınmayan (90g)", nf, "WARN" if nf else "PASS")
        if ns:
            self.add_risk(f"{ns} kez USB güç dalgalanması/aşırı akim (kısa devre benzeri) — bozuk USB cihaz/port; "
                          "elektronik hasar riski, sorunlu cihazı/portu tespit edin.")
        if nf:
            self.add_risk(f"{nf} kez USB aygıt arızası/tanınmama — bozuk USB cihaz takilmis olabilir.")
        for s in surge[-3:]:
            lines.append(f"  ⚡ {s.get('time','')}  {s.get('msg','')[:55]}")
        # --- guvenilirlik derecesi: beklenmedik kapanma sayisina gore (teklestirilmis) ---
        if unexp == 0:
            self.set_grade("Reset", 3)
        elif unexp <= 2:
            self.set_grade("Reset", 2)      # 1-2 olay (kurulumda fis cekilmis olabilir) - İYİ
        elif unexp <= 5:
            self.set_grade("Reset", 1)
        else:
            self.set_grade("Reset", 0)
        # --- elektrik kesintisi <-> SSD korelasyonu ---
        if unexp > 0:
            disk_g = self.grades.get("Disk", 3)
            if disk_g <= 1:
                self.add_risk(f"{unexp} beklenmedik kapanma (elektrik?) VE disk sağlık/bütünlüğü zayif — "
                              "SSD elektrik kesintisinden zarar görmüş olabilir, DEGISTIRMEYI düşünün.")
            else:
                self.add_risk(f"{unexp} beklenmedik kapanma (elektrik?) — SSD'ler bundan bozulabilir; "
                              "sahada UPS/kesintisiz güç önerilir.")
        # --- kritik olaylar (WHEA / disk / BSOD) + kayit kapsami ---
        crit = crit or {}
        self.critical = crit
        whea = crit.get("whea") or 0
        diskerr = crit.get("diskerr") or 0
        bsod = crit.get("bsod") or 0
        oldest = crit.get("log_oldest") or ""
        rstatus = "WARN" if unexp else "PASS"
        lines.append("")
        lines.append(f"Donanim hatasi (WHEA): {whea}   |   Disk/dosya sistemi hatasi: {diskerr}   |   Mavi ekran (BSOD): {bsod}")
        self.record("Kritik", "Donanim hatasi (WHEA)", whea, "FAIL" if whea else "PASS")
        self.record("Kritik", "Disk/dosya sistemi hatasi", diskerr, "WARN" if diskerr else "PASS")
        self.record("Kritik", "Mavi ekran (BSOD)", bsod, "WARN" if bsod else "PASS")
        if whea:
            self.add_risk(f"{whea} WHEA donanim hatasi (CPU/RAM/PCIe) — ciddi; donanimi kontrol edin/degistirin.")
            rstatus = "FAIL"
        if diskerr:
            self.add_risk(f"{diskerr} disk/dosya sistemi hatasi olayi — disk veya kablo/baglanti sorunu olabilir.")
            if rstatus == "PASS":
                rstatus = "WARN"
        if bsod:
            self.add_risk(f"{bsod} mavi ekran (BSOD) olayi — sistem kararsizligi, surucu/donanim incelenmeli.")
            if rstatus == "PASS":
                rstatus = "WARN"
        if oldest:
            inst = (self.inv or {}).get("os_install", "")
            lines.append(f"Kayit kapsami: en eski log {oldest}" + (f"  |  Windows kurulum {inst}" if inst else ""))
            self.record("Kritik", "Log baslangici", oldest, "INFO")
        self.finish_auto("reset", rstatus, lines)

    # ===================== 9) OZET =====================
    def step_summary(self):
        b = self._shell()
        fails = sum(1 for *_, s in self.rows if s == "FAIL")
        warns = sum(1 for *_, s in self.rows if s == "WARN")
        verdict = "RED (FAIL)" if fails else ("ŞARTLI (WARN)" if warns else "GEÇTİ (PASS)")
        vcol = RED if fails else (YEL if warns else GREEN)

        head = ""
        if self.inv:
            head = f"{self.inv.get('computer','')}   |   S/N: {self.sn_var.get() or self.inv.get('serial','')}"
        if self.op_var.get():
            head += f"   |   Operatör: {self.op_var.get()}"
        tk.Label(b, text="TEST OZETI", font=("Segoe UI", 20, "bold"), fg=FG, bg=BG).pack(anchor="w", padx=40, pady=(14, 0))
        tk.Label(b, text=head, font=("Segoe UI", 11), fg=MUT, bg=BG).pack(anchor="w", padx=40)

        # Genel/toplu not YOK — sadece test sonucu (sayisal) + her donanımin kendi notu.
        tk.Label(b, text=f"Test sonucu: {verdict}   (FAIL={fails}  WARN={warns})",
                 font=("Segoe UI", 15), fg=vcol, bg=BG).pack(anchor="w", padx=40, pady=8)
        tk.Label(b, text="Her donanım KENDI karakteristiğine gore değerlendirilir:",
                 font=("Segoe UI", 12), fg=MUT, bg=BG).pack(anchor="w", padx=40)

        # --- her donanım icin ayri not karti ---
        order = [("Ekran", "Ekran"), ("Dokunmatik", "Dokunmatik"), ("CPU", "CPU"),
                 ("Soğutma", "Soğutma"), ("Adaptör", "Adaptör"), ("RAM", "RAM"),
                 ("Disk", "Disk/SSD"), ("Çipset", "Çipset"), ("USB", "USB"),
                 ("Ag", "Ağ"), ("Reset", "Güvenilirlik")]
        cards = tk.Frame(b, bg=BG); cards.pack(anchor="w", padx=36, pady=4)
        col = 0
        for key, disp in order:
            if key not in self.grades:
                continue
            g = self.grades[key]
            cf = tk.Frame(cards, bg=PANEL, highlightbackground=GRADE_COLORS[g], highlightthickness=2)
            cf.grid(row=col // 5, column=col % 5, padx=5, pady=4, sticky="n")
            tk.Label(cf, text=disp, font=("Segoe UI", 11), fg=MUT, bg=PANEL).pack(padx=12, pady=(8, 0))
            tk.Label(cf, text=GRADE_LABELS[g], font=("Segoe UI", 12, "bold"),
                     fg=GRADE_COLORS[g], bg=PANEL).pack(padx=12, pady=(0, 8))
            col += 1

        # --- saha risk uyarilari ---
        if self.risks:
            rf = tk.Frame(b, bg="#2b2410", highlightbackground=YEL, highlightthickness=1)
            rf.pack(fill="x", padx=40, pady=6)
            tk.Label(rf, text="⚠ SAHA RİSK UYARILARI (değiştir/kontrol et)", font=("Segoe UI", 13, "bold"),
                     fg=YEL, bg="#2b2410").pack(anchor="w", padx=12, pady=(8, 2))
            for m in self.risks:
                tk.Label(rf, text="• " + m, font=("Segoe UI", 11), fg="#f0d890", bg="#2b2410",
                         wraplength=self.sw - 420, justify="left").pack(anchor="w", padx=18, pady=1)
            tk.Label(rf, text="", bg="#2b2410").pack(pady=2)
        else:
            tk.Label(b, text="✓ Donanım karakteristiklerinde saha riski tespit edilmedi.",
                     font=("Segoe UI", 12), fg=GREEN, bg=BG).pack(anchor="w", padx=40, pady=2)

        wrap = tk.Frame(b, bg=BG); wrap.pack(fill="both", expand=True, padx=40, pady=6)
        txt = tk.Text(wrap, bg=PANEL, fg=FG, font=("Consolas", 11), relief="flat", height=10)
        txt.pack(fill="both", expand=True)
        for cat, item, val, st in self.rows:
            txt.insert("end", f"[{st:<4}] {cat:<10} {item:<22} {val}\n")
        txt.config(state="disabled")

        path = self._write_report(verdict, fails, warns)
        link = tk.Label(b, text="📄 Rapor (açmak için tıkla): " + path, font=("Segoe UI", 11, "underline"),
                        fg=ACC, bg=BG, cursor="hand2")
        link.pack(anchor="w", padx=40, pady=6)
        link.bind("<Button-1>", lambda e: _open(path))

        btns = tk.Frame(b, bg=BG); btns.pack(pady=14)
        tk.Button(btns, text="Raporu Aç", font=("Segoe UI", 14), bg=PANEL, fg=FG, relief="flat",
                  padx=18, pady=8, command=lambda: _open(path)).pack(side="left", padx=8)
        tk.Button(btns, text="Yeni Test", font=("Segoe UI", 14), bg=GREEN, fg="#06210f", relief="flat",
                  padx=18, pady=8, command=self._restart).pack(side="left", padx=8)
        tk.Button(btns, text="Çıkış", font=("Segoe UI", 14), bg=RED, fg="#2a0a0a", relief="flat",
                  padx=18, pady=8, command=self._quit).pack(side="left", padx=8)

    def _write_report(self, verdict, fails, warns):
        stamp = time.strftime("%Y%m%d_%H%M%S")
        comp = (self.inv or {}).get("computer", os.environ.get("COMPUTERNAME", "PC"))
        path = os.path.join(base_dir(), f"test_{comp}_{stamp}.html")
        ev = self.reset_events or []
        cU = getattr(self, "reset_unexp", None)
        if cU is None:
            cU = count_unexpected(ev)
        if ev:
            reset_rows = "".join(
                "<tr class='{cls}'><td>{t}</td><td>{ty}</td><td>{d}</td></tr>".format(
                    cls=("fail" if e.get("type") == "BEKLENMEDIK" else ("warn" if e.get("type") == "SOFT" else "")),
                    t=e.get("time", ""), ty=e.get("type", ""), d=e.get("detail", ""))
                for e in reversed(ev))    # en yeni tarih ustte
            reset_html = ("<h2>Reset / Elektrik Geçmişi (son 90 gun) &mdash; beklenmedik: "
                          f"<b>{cU}</b></h2><p class='mut'>BEKLENMEDIK = elektrik kesintisi "
                          "veya manuel/hard-reset</p><table><tr><th>Zaman</th><th>Tip</th>"
                          f"<th>Aciklama</th></tr>{reset_rows}</table>")
        else:
            reset_html = "<p class='mut'>Reset geçmişi alinamadi.</p>"
        # USB güç/arıza olaylari (reset raporuna ekli)
        surge = (self.usb_events or {}).get("surge") or []
        fault = (self.usb_events or {}).get("fault") or []
        if surge or fault:
            urows = "".join(
                f"<tr class='{c}'><td>{e.get('time','')}</td><td>{t}</td><td>{e.get('msg','')}</td></tr>"
                for t, c, lst in (("USB GÜÇ/AŞIRI AKIM", "fail", surge), ("USB ARIZA", "warn", fault))
                for e in reversed(lst))
            reset_html += ("<h2>USB Güç / Arıza Olaylari (son 90 gun)</h2>"
                           f"<p class='mut'>Güç dalgalanması/aşırı akim: <b>{len(surge)}</b> &nbsp; "
                           f"Arıza/tanınmayan: <b>{len(fault)}</b></p>"
                           f"<table><tr><th>Zaman</th><th>Tip</th><th>Olay</th></tr>{urows}</table>")
        else:
            reset_html += "<p class='mut'>USB güç/arıza olayi yok.</p>"
        if self.risks:
            risk_items = "".join(f"<li>{m}</li>" for m in self.risks)
            risk_html = ("<div class='riskbox'><b>⚠ SAHA RİSK UYARILARI (değiştir/kontrol et)</b>"
                         f"<ul>{risk_items}</ul></div>")
        else:
            risk_html = "<p style='color:#3fb950'>✓ Donanım karakteristiklerinde saha riski tespit edilmedi.</p>"
        vcls = "fail" if fails else ("warn" if warns else "pass")
        rows = "\n".join(
            f"<tr class='{s.lower()}'><td>{s}</td><td>{c}</td><td>{i}</td><td>{v}</td></tr>"
            for c, i, v, s in self.rows)
        # Genel/toplu not YOK — sadece her donanım icin KENDI karakteristik notu (rozet)
        grade_order = [("Ekran", "Ekran"), ("Dokunmatik", "Dokunmatik"), ("CPU", "CPU"),
                       ("Soğutma", "Soğutma"), ("Adaptör", "Adaptör"), ("RAM", "RAM"),
                       ("Disk", "Disk/SSD"), ("Çipset", "Çipset"), ("USB", "USB"),
                       ("Ag", "Ağ"), ("Reset", "Güvenilirlik")]
        chips = "".join(
            f"<span class='chip' style='border-color:{GRADE_COLORS[self.grades[k]]};color:{GRADE_COLORS[self.grades[k]]}'>"
            f"{disp}: {GRADE_LABELS[self.grades[k]]}</span>"
            for k, disp in grade_order if k in self.grades)
        grade_html = (f"<h2 style='font-size:15px'>Donanım notlari (her biri kendi karakteristiğine gore)</h2>"
                      f"<div>{chips}</div>") if chips else ""
        op = self.op_var.get(); sn = self.sn_var.get()
        inv = self.inv or {}
        _uri = logo_data_uri()
        logo_tag = f"<div class='logobox'><img src='{_uri}'></div>" if _uri else ""
        html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Test {comp}</title>
<style>body{{background:#0d1117;color:#c9d1d9;font-family:Segoe UI,Arial;margin:24px}}
h1{{font-size:22px}}.mut{{color:#8b949e}}table{{border-collapse:collapse;width:100%;margin-top:12px}}
td,th{{border:1px solid #30363d;padding:6px 12px;text-align:left}}th{{background:#161b22}}
.pass{{background:#0f2d1a}}.fail{{background:#3d1414}}.warn{{background:#3d3414}}.info{{}}
.v{{font-size:20px;font-weight:bold;padding:10px 16px;border-radius:8px;display:inline-block;margin:10px 0}}
.logobox{{display:inline-block;background:#fff;padding:6px 12px;border-radius:6px;margin-bottom:8px}}
.logobox img{{height:40px;display:block}}
.riskbox{{background:#2b2410;border:1px solid #d29922;border-radius:8px;padding:10px 16px;margin:12px 0;color:#f0d890}}
.riskbox b{{color:#d29922}}
.grade{{font-size:22px;font-weight:bold;color:#0d1117;padding:12px 18px;border-radius:8px;display:inline-block;margin:10px 0}}
.chip{{display:inline-block;border:2px solid;border-radius:16px;padding:4px 12px;margin:3px;font-weight:bold;font-size:13px}}
</style></head><body>
{logo_tag}
<h1>Dokunmatik PC - Tam Test Raporu  <span class='mut' style='font-size:13px'>v{APP_VERSION}</span></h1>
<p class='mut'>{comp} &nbsp;|&nbsp; S/N: {sn or inv.get('serial','')} &nbsp;|&nbsp; Operatör: {op or '-'} &nbsp;|&nbsp; {inv.get('board','')} &nbsp;|&nbsp; {time.strftime('%Y-%m-%d %H:%M:%S')}</p>
{grade_html}
<div class='v {vcls}'>SONUC: {verdict} &nbsp; (FAIL={fails} WARN={warns})</div>
{risk_html}
<table><tr><th>Durum</th><th>Kategori</th><th>Test</th><th>Deger</th></tr>
{rows}</table>
{reset_html}</body></html>"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(html)
        except Exception:
            pass
        return path

    def _restart(self):
        self.rows = []; self.inv = None; self.step_state = {}; self.i = -1
        self._intro()

    def _quit(self):
        self.root.destroy()

    def _on_resize(self, e):
        if e.widget is self.root:
            self.sw = max(400, self.root.winfo_width())
            self.sh = max(300, self.root.winfo_height())

    def _toggle_fs(self, _=None):
        self._fs = not self._fs
        try:
            self.root.attributes("-fullscreen", self._fs)
        except Exception:
            pass


def ch_safe(rows):
    return rows if rows else 1


def _open(path):
    try:
        os.startfile(path)  # type: ignore
    except Exception:
        pass


def selftest():
    # frozen exe risk kontrolleri: gomulu logo + multiprocessing
    lp = resource_path("logo.png")
    print("Logo bulundu:", os.path.exists(lp), "->", lp)
    t = time.time()
    procs = [mp.Process(target=_cpu_worker, args=(2,)) for _ in range(min(4, os.cpu_count() or 2))]
    for p in procs: p.start()
    for p in procs: p.join()
    print(f"Multiprocessing OK ({len(procs)} proc, {time.time()-t:0.1f}s)")
    print("Inventory:", json.dumps(ps_json(PS_INVENTORY), ensure_ascii=False)[:400])
    print("Temp:", read_temp())
    print("SSD (64MB):", ssd_speed(64))
    print("RAM(64MB) ok:", ram_verify(64))
    print("Network:", json.dumps(ps_json(PS_NETWORK), ensure_ascii=False)[:300])
    print("Reset30:", run_ps(PS_RESET30, 20))


if __name__ == "__main__":
    mp.freeze_support()
    if "--selftest" in sys.argv:
        selftest()
    else:
        root = tk.Tk()
        Wizard(root)
        root.mainloop()
