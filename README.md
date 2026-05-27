# Dokunmatik PC – Donanım Test Aracı (Endutek)

Üretim hattında her PC'yi (CPU / RAM / SSD / Ağ / GPU / BIOS + ekran + dokunmatik)
hızlıca test etmek için araç seti. Kurulum gerektirmez.
J1900, i5 3.nesil gibi düşük güçlü/eski anakartlarda da çalışır.

## ⭐ `Endutek-PC-Test.exe` — Hepsi bir arada (önerilen)

Çift tıkla; tek programda **sırayla otomatik** tüm testler:
1. Ekran (renk/dead-pixel) → operatör onayı
2. Dokunmatik çizim → operatör onayı
3. Dokunmatik ızgara kapsama
4. Donanım envanteri (CPU/RAM/Disk/SMART/GPU)
5. **CPU/RAM stres (burn-in)** — süre açılışta seçilir: 1 dk / 5 dk / 30 dk / 1 saat / 2 saat / özel.
   5 dk+ testlerde sıcaklık 15 sn'de bir CSV'ye loglanır, peak sıcaklık limitle (95°C) karşılaştırılır.
6. SSD hız (oku/yaz)
7. Ağ / internet
8. Reset / elektrik geçmişi (son 30 gün; soft / temiz / beklenmedik sınıflandırma)
9. Özet + logolu HTML rapor (exe klasörüne yazılır)

Kaynağı: `pc_full_test.py`. Yeniden derleme:
`pip install pyinstaller pillow` → `pyinstaller --onefile --noconsole --uac-admin --add-data "logo.png;." --icon app.ico pc_full_test.py`

Aşağıdaki tekil araçlar (PowerShell/GUI) ayrı kullanım/derleme içindir:

## 1) `Test-Hardware.ps1` — Donanım envanteri + stress + sağlık (PowerShell)

Otomatik toplar ve **beklenen değerlerle karşılaştırır** (PASS/WARN/FAIL):
- Anakart / BIOS / seri no / işletim sistemi
- CPU model, çekirdek, hız
- RAM: slot başına kapasite/hız/üretici + toplam kontrol
- Disk: model, kapasite, **SMART sağlık** (sıcaklık, aşınma, hata sayaçları, çalışma saati)
- GPU + çözünürlük/tazeleme
- Ağ: Ethernet/WiFi link durumu, hız, MAC, internet ping
- **Stress:** tüm çekirdeklere CPU yükü + RAM yaz/oku doğrulama + CPU sıcaklığı (okunabilirse)
- **SSD hız:** ardışık yazma/okuma MB/s

### Çalıştırma
PowerShell'i **Yönetici** olarak aç (SMART/sıcaklık için gerekir):
```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
cd D:\pc-test-tool
.\Test-Hardware.ps1                       # tam test (20 sn stress)
.\Test-Hardware.ps1 -SkipStress           # sadece hızlı envanter
.\Test-Hardware.ps1 -StressSeconds 60 -Html   # 60 sn stress + HTML rapor
```

### Üretim hattına uyarlama
Script başındaki **`$Expected`** bloğunu kendine göre ayarla
(min RAM, min disk, min SSD hızı, max CPU sıcaklığı, Ethernet/WiFi zorunlu mu).
FAIL varsa script **çıkış kodu 1** döner — hat otomasyonuna bağlanabilir.

### Rapor
Aynı klasöre `<BilgisayarAdı>_<tarih>.txt` (ve `-Html` ile `.html`) yazılır;
seri no içerdiği için arşivlenebilir.

## 2) `display_touch_test.py` — Ekran + dokunmatik görsel test (Python GUI)

Tam ekran menü, 5 test:
1. **Renk doldurma** – dead pixel / renk bozukluğu (kırmızı/yeşil/mavi/beyaz/siyah/gri…)
2. **Gradyan / ızgara** – panel uniform mu, geometri/overscan doğru mu
3. **Dokunmatik çizim** – kesintisiz iz takibi
4. **Dokunmatik ızgara kapsama** – ekranın her hücresine dokunulduğunu doğrular
5. **Çok-nokta (multitouch)** – eşzamanlı temas görselleştirme

`ESC` veya sağ tık → menüye döner. Renk/desen testlerinde sol tık/boşluk → sonraki.

### Çalıştırma
```powershell
python display_touch_test.py
```
(Standart Python 3.8+ yeter; ek paket gerekmez — tkinter Python'la gelir.)

## 3) `Burn-In-Test.ps1` — uzun süreli dayanıklılık (burn-in) testi

Varsayılan **2 saat** tüm çekirdekleri yükler, belirli aralıklarla ölçüm alıp
**CSV'ye canlı loglar** ve sonunda **grafikli HTML rapor** üretir
(CPU yükü / sıcaklık / saat-throttle / disk sıcaklığı / WHEA donanım hatası).

```powershell
.\Burn-In-Test.ps1                       # 2 saat, 15 sn örnekleme
.\Burn-In-Test.ps1 -DurationMinutes 30   # kısa deneme
.\Burn-In-Test.ps1 -DurationMinutes 120 -SampleSeconds 10 -RamStressMB 1024
.\Burn-In-Test.ps1 -FromCsv .\burnin_PC_tarih.csv   # eski logdan raporu yeniden üret
```
- Test kesilse (Ctrl+C / elektrik) bile **CSV'deki veri korunur**; `-FromCsv` ile
  rapor sonradan yeniden üretilir → **raporu istediğin zaman açıp incelersin**.
- **WHEA** donanım hatası veya CPU `MaxCpuTempC` aşımı → **FAIL** + çıkış kodu 1.
- Rapor, test penceresinde olan **reset/kapanma olaylarını** da listeler.

## 4) `Reboot-History.ps1` — reset / kapanma / elektrik kesintisi geçmişi

Cihazın **ne zaman ve nasıl** yeniden başladığını sınıflandırır (Windows olay
günlüğünden — ayrı servise gerek yok, çünkü Windows bunu kalıcı loglar):
- **TEMİZ KAPANMA** – düzgün shutdown
- **SOFT-RESET** – kullanıcı/OS başlattı (planlı reboot; başlatan işlem/neden yazılır)
- **BEKLENMEDİK** – elektrik kesintisi **veya** manuel/hard-reset / crash
- **AÇILIŞ** – sistem açılışı

```powershell
.\Reboot-History.ps1               # son 30 gün → ekran + HTML + CSV
.\Reboot-History.ps1 -Days 90
.\Reboot-History.ps1 -Install      # AÇILIŞTA otomatik rapor üreten görevi kur ("servis gibi")
.\Reboot-History.ps1 -Uninstall    # görevi kaldır
```
> Not: 6008 / Kernel-Power 41 olayları "elektrik kesintisi" ile "manuel/hard-reset
> düğmesi"ni **ayırt edemez** — ikisi de Windows'a kirli kapanma olarak görünür.

## Hazır `.exe` dosyaları (çift tıkla çalışır — kurulum yok)

Başka PC'ye sadece şu exe'leri kopyalaman yeter; Python/PowerShell gerekmez:

| Exe | Karşılığı |
|---|---|
| `DonanimTesti.exe` | `Test-Hardware.ps1` — envanter + stress + SSD + ağ |
| `BurnInTesti.exe` | `Burn-In-Test.ps1` — 2 saat burn-in + grafikli rapor |
| `ResetGecmisi.exe` | `Reboot-History.ps1` — reset/elektrik geçmişi |
| `EkranDokunmatikTest.exe` | `display_touch_test.py` — ekran + dokunmatik GUI |

- İlk üçü **Yönetici** ister → çift tıklayınca **UAC onayı** çıkar (SMART/sıcaklık/WHEA için gerekli).
- Raporlar (`.txt/.html/.csv`) exe'nin bulunduğu **klasöre** yazılır.
- Parametre vermek için komut satırından: `BurnInTesti.exe -DurationMinutes 120`.
- İmzasız oldukları için SmartScreen "Daha fazla bilgi → Yine de çalıştır" gerekebilir.

> Exe'leri kendin yeniden üretmek istersen: `Install-Module ps2exe`, sonra
> `Invoke-ps2exe -inputFile Test-Hardware.ps1 -outputFile DonanimTesti.exe -requireAdmin`.

## Tek `.exe`'ye paketleme (kaynak — opsiyonel)
Hatta Python kurmadan dağıtmak için GUI'yi tek dosyaya çevir:
```powershell
pip install pyinstaller
pyinstaller --onefile --noconsole display_touch_test.py
# -> dist\display_touch_test.exe
```
PowerShell scriptini de bir `.bat` ile sarıp masaüstüne kısayol koyabilirsin.

## Önerilen üretim akışı
1. `Test-Hardware.ps1` (yönetici) → envanter/stress/SSD/ağ raporu, PASS/FAIL.
2. `display_touch_test.py` → ekran + dokunmatik görsel kontrol.
3. Raporları seri no ile arşivle.
