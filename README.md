# تهران ژئوکدر — Tehran Geocoder

تبدیل آدرس فارسی به لوکیشن برای تهران — **کاملاً لوکال و آفلاین**، با مدل ML که از اصلاحات کاربر یاد می‌گیرد.

Convert free-form Persian addresses to coordinates in Tehran. Fully local/offline,
with a self-learning loop: every user correction improves the next answer.

## ویژگی‌ها
- پارس آدرس آزاد فارسی با مدل **CRF** آموزش‌دیده روی دیتای مصنوعی ساخته‌شده از اسم‌های واقعی تهران
- **پیشنهاد چندگانه با درصد تطابق**: همهٔ خیابان‌های همنام (مثلاً ۵ تا «اکبری») با امتیاز نمایش داده می‌شوند
- نرمال‌سازی فارسی: اعداد ۱۲/١٢/12، ي/ك عربی، نیم‌فاصله، مخفف‌ها (خ، ک، پ، ط)
- تشخیص **منطقه ۲۲گانه و محله** با point-in-polygon
- **حلقه یادگیری**: اصلاح کاربر → ایندکس فوری + بازآموزی دوره‌ای (با golden-set gate و نسخه‌بندی مدل)
- نقشه آفلاین (فاز بعد: planetiler) — دمو فعلاً از تایل OSM استفاده می‌کند

## منابع دیتا (همه باز)
- OpenStreetMap Iran extract © OpenStreetMap contributors (ODbL) — Geofabrik
- [tehran-districts-neighborhoods-map-geojson](https://github.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson) — پلیگون مناطق/محله‌ها
- [Tehran-address](https://github.com/thisistayeb/Tehran-address) (MIT) — ۵۰۰۰+ نقطه برای seed/تست
- الهام از [persian-address-parser](https://github.com/rezadev8/persian-address-parser) (MIT) برای قواعد نرمال‌سازی

## اجرا

```bash
pip install -r requirements.txt

# 1) دیتا (یک‌بار؛ بعدش کاملاً آفلاین)
python scripts/download_data.py          # geojson + csv
python scripts/download_data.py --pbf    # اکسترکت OSM ایران (~220MB)

# 2) ایندکس تهران
python scripts/seed_from_csv.py          # seed سریع از CSV (برای دمو)
python scripts/build_index.py            # ایندکس کامل از OSM (بعد از دانلود PBF)

# 3) مدل ML
python ml/generate_data.py --count 25000
python ml/train_parser.py

# 4) سرور + دمو
uvicorn backend.app:app --port 8000
# → http://localhost:8000
```

## API
| endpoint | کار |
|---|---|
| `GET /api/geocode?q=...` | کاندیدهای رتبه‌بندی‌شده با `match` (درصد) + فیلدهای پارس‌شده |
| `GET /api/autocomplete?q=...` | پیشنهاد اسم خیابان |
| `GET /api/reverse?lat=&lng=` | نزدیک‌ترین خیابان + منطقه/محله |
| `POST /api/feedback` | ثبت اصلاح کاربر → یادگیری |
| `GET /api/stats` | وضعیت دیتابیس و مدل |

## معماری یادگیری
دیتا منبع حقیقت است؛ مدل تابعی یک‌بارمصرف از دیتاست:
1. اصلاح کاربر فوراً وارد ایندکس می‌شود (بدون بازآموزی)
2. بازآموزی CRF از صفر روی دیتای تمیز (چند دقیقه، CPU)
3. **golden set** (~۲۰ آدرس ثابت) دروازهٔ پذیرش مدل جدید است
4. مدل‌ها نسخه‌بندی می‌شوند → rollback همیشه ممکن

## سخت‌افزار هدف
۸ گیگ رم، CPU-only (بدون GPU). مصرف رم در اجرا ~۱–۲ گیگ.

## License
MIT (کد). دیتای OSM: ODbL — attribution را در UI نگه دارید.