# مساعد بلاغات الصيانة

المشروع يستخدم React وFastAPI وLangGraph وSQLite، مع ASL-4B-v1 محليًا وRAG فعلي عبر Sentence Transformers وFAISS.

المسار: استخراج البلاغ ← تقييم الخطر ← التحقق من المعلومات ← مطابقة الجهاز ← استرجاع الإجراءات ← اختيار الإجراءات من ASL ← حفظ التذكرة.

- الموقع غير المسجل يرجع `asset_not_found` بدون تذكرة.
- تعدد الأجهزة يرجع `needs_asset_selection`؛ الاختيار لازم يكون من المرشحين وفي الخدمة وقت الاستكمال.
- التحذير يظهر مع سؤال المتابعة أو اختيار الجهاز إذا اكتُشف خطر.
- التوصية تستخدم نص المرجع كاملًا، وتحفظ نسخة الإجراء ومصدره مع التذكرة.
- المراجع الحالية إجراءات المشروع، وليست اعتمادًا من الشركة المصنعة. نقص التغطية يظهر `partial` أو `manual_review`.
- `/ready` يوضح تشغيل النموذج والـRAG فعليًا. وضع الاختبار heuristic معلن ولا يحل محل ASL عند فشله.

## التشغيل

جهّز Python ومكتبات backend وASL والـRAG أولًا حسب [دليل backend](backend/README.md). على Windows بدون NVIDIA، المحرك المناسب الموجود بالمشروع هو llama.cpp مع GGUF Q4_K_M من أوزان ASL الرسمية.

```powershell
cd backend
python scripts/setup_db.py
uvicorn app.main:app --reload --port 8000
```

وفي نافذة ثانية:

```powershell
cd frontend
npm install
npm run dev
```

الواجهة على http://localhost:5173، وفحص الجاهزية على http://localhost:8000/ready.

## التحقق

```powershell
cd backend
python -m pytest -q
```

```powershell
cd frontend
npm run build
$env:BACKEND_PYTHON='C:/path/to/python.exe'
npm run test:e2e
```

اختبارات المتصفح تستخدم قاعدة مؤقتة ومنافذ 8018 و5178، ووضع heuristic ومتجهات اختبار معلنة. اختبار ASL والبحث الحقيقي منفصل؛ راجع [معايير القبول](docs/TESTING.md). ما فيه مسارات قراءة اختبارية في تطبيق الإنتاج.
