# Endutek — Dokunmatik PC Donanım Test Aracı

Üretim hattında her PC'yi (ekran, dokunmatik, CPU, RAM, SSD/disk, ağ, GPU, BIOS)
hızlıca **test eden, derecelendiren ve sahada sorun çıkaracak donanımı önceden uyaran**
araç seti. Kurulum gerektirmez; çift tıkla çalışır.
J1900, i5 3.nesil gibi düşük güçlü/eski anakartlarda da çalışır ve
**donanımı kendi sınıfına göre adil değerlendirir** (eski diye "kötü" demez).

---

## ⭐ `Endutek-PC-Test.exe` — Hepsi bir arada (ana program)

Çift tıkla → tam ekran test istasyonu. Üstte logo + canlı saat + makine adı.

### Açılış ekranı
- **Operatör adı + Seri No / İş emri** girişi (rapora yazılır, izlenebilirlik)
- **Test seçimi (tikler):** hangi testlerin yapılacağını işaretle; sadece işaretliler sırayla çalışır
- **Stres süresi:** 1 dk / 5 dk / 30 dk / 1 saat / 2 saat veya **özel dakika**

### Testler — ne'yi nasıl test ediyor

**1. Ekran (renk / dead-pixel)**
Tam ekran kırmızı/yeşil/mavi/beyaz/siyah/gri desenler gösterir. Operatör ölü piksel,
renk/parlaklık sorununa bakıp **GEÇTİ/HATALI** işaretler.

**2. Dokunmatik çizim**
Parmakla çizim; izin kesintisiz çıkıp çıkmadığına operatör karar verir (dokunmatik
tepkisi/ölü bölge kontrolü).

**3. Dokunmatik ızgara kapsama**
Ekran 8×5 hücreye bölünür; operatör her hücreye dokunur. Hepsi yeşil olunca otomatik
geçer → ekranın **her noktasının** dokunmatik algıladığı doğrulanır.

**4. Donanım envanteri**
WMI/CIM ile otomatik toplar: anakart, BIOS, **seri no**, OS, CPU (model/çekirdek),
**RAM** (miktar + kanal sayısı), **disk** (model/kapasite/medya/bus + SMART), GPU,
çözünürlük. Beklenen değerlerle karşılaştırır (RAM/disk min vb.).

**4b. BIOS / CMOS pili**
BIOS sürüm/tarihi raporlanır. **CMOS/BIOS düğme pili (CR2032)** — anakart üzerindeki ayrı
pil, pilsiz sistemlerde de var — **bittiğinde saat sıfırlanır**. Sistem yılı mantıksız
(BIOS tarihinden eski) ise pil bitmiş kabul edilip uyarılır (sahada tarih/lisans/sertifika
sorunlarını önler).

**5. CPU / RAM stres (burn-in) + soğutma + adaptör**
Tüm çekirdeklere seçilen süre boyunca **tam yük** bindirir.
- 15 sn'de bir **sıcaklık + CPU saati + güç durumu** örneklenir, **peak sıcaklık** tutulur
- 5 dk+ testlerde sıcaklık/saat `burnin_*.csv`'ye **canlı loglanır**
- Yük sonrası **RAM yaz/oku doğrulaması** (0xAA / 0x55 deseni)
- **Soğutma yeterli mi:** peak sıcaklık + **throttle** (CPU saati yük altında düşüyor mu).
  Sıcaklık yüksek + saat düşüyorsa → soğutma yetersiz.
- **Adaptör/güç iyi mi:** pilsiz (DC) cihazda sıcaklık düşükken throttle varsa →
  güç/adaptör sınırı şüphesi. (Pilli cihazda: fişe takılıyken yükte pil boşalıyorsa adaptör zayıf.)

**6. SSD / Disk — sağlık + hız + bütünlük**  *(elektrik kesintisi hasarına özel)*
- **Hız:** ardışık yazma/okuma MB/s
- **Veri bütünlüğü:** yazılan veri geri okunup **birebir karşılaştırılır** → bozuk/zayıf
  blok, sessiz bozulma yakalanır (sadece hız değil)
- **Dosya sistemi "kirli bit"** (`fsutil dirty`): son kapanma düzgün müydü
- **Disk taraması** (`Repair-Volume -Scan`, salt-okunur): dosya sistemi bozulması var mı
- SMART: sağlık, aşınma %, sıcaklık, okuma/yazma hata sayacı, çalışma saati (4. adımda)

**7. Ağ / internet**
Ethernet/WiFi adaptörleri: link durumu, hız (Mbps), MAC + internet **ping** (8.8.8.8).

**8. Reset / elektrik geçmişi (son 30 gün)**
Windows olay günlüğünden kapanma/açılma olaylarını sınıflandırır:
**TEMİZ kapanma / SOFT-reset / BEKLENMEDİK (elektrik kesintisi veya hard-reset) / AÇILIŞ**.
Beklenmedik kapanma + zayıf disk birlikteyse **SSD elektrik hasarı** uyarısı verir.

**9. Özet + rapor**
Genel değerlendirme banner'ı, her donanım için not kartı, risk paneli, sonuç tablosu;
logolu **HTML rapor** exe klasörüne yazılır.

---

## 🏅 Derecelendirme — her donanım için ayrı

Her bileşen 4 seviye not alır: **ÇOK KÖTÜ / KÖTÜ / İYİ / SÜPER**.
Genel not = en zayıf bileşen (zincir en zayıf halkası kadar sağlam).

Notlar **donanımın kendi karakteristiğine göre** (eski/yavaş donanım adil değerlendirilir):
| Donanım | Neye göre |
|---|---|
| **CPU** | Ham hız değil → yük altında **sıcaklık marjı / throttle yok mu**. Sıcaklık okunamazsa cezalandırmaz. |
| **RAM** | Sağlık (yaz/oku doğrulama) + dual-channel; düşük GB diye değil. |
| **Disk/SSD** | Hız **medya tipine göre** (HDD ~60/90, SATA SSD ~250/350, NVMe ~700/1500 MB/s) + SMART sağlık + **veri bütünlüğü** + dosya sistemi durumu. |
| **Soğutma** | Yük altında peak sıcaklık + throttle (yüksek sıcaklık + saat düşüşü = yetersiz). |
| **Adaptör** | Yük altında güç sınırı/throttle veya (pilli ise) pil boşalması. |
| **Ekran / Dokunmatik** | Operatör onayı. |
| **Ağ** | Link + internet erişimi. |
| **Güvenilirlik** | Son 30 gün beklenmedik reset sayısı. |

---

## ⚠ Saha risk uyarıları

Geçse bile, **ileride sahada sorun çıkarabilecek** donanımı önceden bildirir:
- Disk sağlığı ≠ Healthy → "değiştir"
- SSD aşınma %≥10, sıcaklık ≥60°C, okuma/yazma hata sayacı > 0
- Çalışma saati ≥100h → "sıfır cihazda kullanılmış disk olabilir"
- **Veri bütünlüğü hatası** → bozuk blok, değiştir
- **Dosya sistemi kirli / tarama bozuk** → elektrik kesintisi hasarı, chkdsk
- **Beklenmedik kapanma + zayıf disk** → SSD elektrik hasarı, UPS önerisi
- **Soğutma yetersiz/sınırda** (peak sıcaklık limite yakın/aştı + throttle)
- **Adaptör/güç sınırı** (yükte throttle ama sıcaklık düşük)
- **CMOS/BIOS pili bitmiş** (saat sıfırlanmış → tarih/lisans sorunu)
- Sistem diski boş alan < 15 GB, tek-kanal RAM

---

## Raporlar
Tüm raporlar exe'nin bulunduğu klasöre yazılır:
- `test_<PC>_<tarih>.html` — tam test raporu (logo, genel not, donanım rozetleri, riskler, tablo, reset geçmişi)
- `burnin_<PC>_<tarih>.csv` — uzun stres testinde sıcaklık logu

---

## Tekil araçlar (ayrı kullanım / PowerShell)
Ana exe çoğu ihtiyacı karşılar; bunlar özel durumlar için:
- **`BurnInTesti.exe`** / `Burn-In-Test.ps1` — bağımsız uzun burn-in (grafikli HTML rapor)
- **`ResetGecmisi.exe`** / `Reboot-History.ps1` — reset geçmişi + `-Install` ile açılışta otomatik servis
- `Test-Hardware.ps1` — sadece PowerShell envanter/stres/SSD/ağ
- `display_touch_test.py` — sadece ekran/dokunmatik GUI

---

## Başka PC'ye kurulum
USB'ye **`Endutek-PC-Test.exe`** (+ istersen `logo.png`) kopyala → hedef PC'de çift tıkla.
- Python/PowerShell gerekmez. İlk açılışta **UAC onayı** (SMART/sıcaklık/tarama için yönetici gerekli).
- İmzasız olduğu için SmartScreen → "Daha fazla bilgi → Yine de çalıştır".
- Logoyu değiştirmek: exe yanına yeni `logo.png` koy.

## Kaynaktan derleme
```powershell
pip install pyinstaller pillow
pyinstaller --onefile --noconsole --uac-admin --add-data "logo.png;." --icon app.ico pc_full_test.py
```

---
*Endutek — industrial weighing and technology*
