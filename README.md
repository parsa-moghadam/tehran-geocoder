# تهران ژئوکدر — Tehran Geocoder

تبدیل آدرس فارسی به لوکیشن برای تهران — **کاملاً لوکال و آفلاین**، با مدل ML که از اصلاحات کاربر یاد می‌گیرد.

Convert free-form Persian addresses to coordinates in Tehran. Fully local/offline,
with a self-learning loop: every user correction improves the next answer.

## ویژگی‌ها
- پارس آدرس آزاد فارسی با مدل **CRF** آموزش‌دیده روی دیتای مصنوعی ساخته‌شده از اسم‌های واقعی تهران
- **پیشنهاد چندگانه با درصد تطابق**: همهٔ خیابان‌های همنام (مثلاً ۵ تا «اکبری») با امتیاز نمایش داده می‌شوند
- نرمال‌سازی فارسی: اعداد ۱۲/١٢/12، ي/ك عربی، نیم‌فاصله، مخفف‌ها (خ، ک، پ، ط)
- تشخیص **منطقه ۲۲گانه و محله** با point-in-polygon
- **شماره پلاک** از نقشه شهرداری (اختیاری): جستجوی «خیابان اکبری پلاک ۱۲» کاندید سطح-پلاک برمی\u200cگرداند
- **حلقه یادگیری**: اصلاح کاربر → ایندکس فوری + بازآموزی دوره‌ای (با golden-set gate و نسخه‌بندی مدل)
- نقشه آفلاین (فاز بعد: planetiler) — دمو فعلاً از تایل OSM استفاده می‌کند

## منابع دیتا
### منبع باز
- OpenStreetMap Iran extract © OpenStreetMap contributors (ODbL) — Geofabrik
- [tehran-districts-neighborhoods-map-geojson](https://github.com/mjalalimanesh/tehran-districts-neighborhoods-map-geojson) — پلیگون مناطق/محله‌ها
- [Tehran-address](https://github.com/thisistayeb/Tehran-address) (MIT) — ۵۰۰۰+ نقطه برای seed/تست
- الهام از [persian-address-parser](https://github.com/rezadev8/persian-address-parser) (MIT) برای قواعد نرمال\u200cسازی

### نقشه شهرداری تهران (پلاک و اسامی)
- منبع: سرویس عمومی وب\u200cنقشه https://map.tehran.ir (متدهای `Search.doSearch` و `GeoCoder.getPropertyIdCode`)
- **هشدار مجوز**: این دیتا **منبع باز / ODbL نیست** و در این مخزن منتشر نمی\u200cشود. فقط یک\u200cبار در زمان ساخت (build time) دانلود و در `data/raw/` (gitignored) ذخیره می\u200cشود. استفاده از آن تابع شرایط شهرداری تهران است؛ برای هرگونه انتشار یا استفاده تجاری باید مجوز جداگانه بگیرید.
- روش کار: اسامی خیابان\u200cها از جستجوی کلمات کلیدی استخراج می\u200cشوند و **شماره پلاک** از reverse-geocoder مختصات (`plaque` + `property_id`) به\u200cدست می\u200cآید و به نزدیک\u200cترین خیابان موجود در ایندکس متصل می\u200cشود.
- پوشش پلاک به\u200cصورت نمونه\u200cبرداری از نقاط خیابان\u200cهاست (پیش\u200cفرض: یک نقطه در هر خیابان). با `--offset-m 30` و کلمات کلیدی بیشتر می\u200cشود تراکم را بالا برد. این یک محدودیت منبع سرویس است، نه اپلیکیشن.
- در زمان اجرا **هیچ تماسی با شهرداری گرفته نمی\u200cشود** — همه چیز محلی است.

## اجرا

```bash
pip install -r requirements.txt

# 1) دیتا (یک‌بار؛ بعدش کاملاً آفلاین)
python scripts/download_data.py          # geojson + csv
python scripts/download_data.py --pbf    # اکسترکت OSM ایران (~220MB)

# 2) ایندکس تهران
python scripts/seed_from_csv.py          # seed سریع از CSV (برای دمو)
python scripts/build_index.py            # ایندکس کامل از OSM (بعد از دانلود PBF)

# 2b) اختیاری: دیتای شهرداری (اسامی بیشتر + شماره پلاک) — فقط build time
python scripts/download_tehran_municipality.py --concurrency 8
python scripts/import_municipality.py

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
| `GET /api/reverse?lat=&lng=` | نزدیک‌ترین خیابان + منطقه/محله + پلاک (در صورت وجود) |
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
MIT (کد). دیتای OSM: ODbL — attribution را در UI نگه دارید. دیتای شهرداری تهران دارای مجوز جداگانه است و در مخزن نیست (بخش بالا را ببینید).