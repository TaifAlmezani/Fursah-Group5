# AI Maintenance Assistant - Backend 🛠️

Backend system powered by **FastAPI**, **LangGraph**, **RAG (FAISS)**, and the local Saudi Arabic model **`saai-sa/ASL-4B-v1`**.

---

## 🚀 Quick Start (تشغيل سريع)

### تجهيز ASL محلياً

لأجهزة Windows بدون NVIDIA، جهّز تشغيل CPU باستخدام `llama.cpp`:

```powershell
python scripts/setup_llm.py --download-only --model-dir D:/AI/models/ASL-4B-v1
python scripts/setup_cpu_llm.py --model-dir D:/AI/models/ASL-4B-v1 --tools-dir D:/AI/llama.cpp --verify --serve
```

أداة CPU تتحقق من SHA256 للأوزان الرسمية، تستخدم إصدار `b11497` من `llama.cpp`، ثم تحول نفس أوزان ASL إلى GGUF بضغط `Q4_K_M`. تحفظ بصمة الملف الناتج ومصدره بجانبه. عند إعادة تشغيل backend، اضبط `.env`:

```dotenv
LLM_ENGINE=llama_cpp
LLM_SERVER_EXECUTABLE=D:/AI/llama.cpp/runtime/llama-server.exe
LLM_GGUF_PATH=D:/AI/models/ASL-4B-v1/ASL-4B-v1-Q4_K_M.gguf
```

الـbackend يشغّل عملية النموذج تلقائيًا على `127.0.0.1:8081`، ويقفل العملية التي شغّلها عند الخروج. لا يستخدم خدمة خارجية. `/ready` يعرض المحرك الفعلي. فشل النموذج يرجع خطأ بدون استبداله بنتيجة heuristic.

من مجلد `backend` وببيئة Python مخصصة للمشروع:

```powershell
python -m pip install -e ".[local-llm,dev]"
python scripts/setup_llm.py
uvicorn app.main:app --port 8000
```

Setup ينزّل الأوزان الرسمية مرة واحدة ثم يختبر التوليد، استخراج JSON، اكتشاف خطر كهربائي وصياغة توصية. يفشل بـexit code غير صفر ويكتب نتيجة النجاح في `data/reports/llm-verification.json`. استخدم `--download-only` للتنزيل أو `--verify-only` لفحص الملفات الموجودة. `--model-dir` يحدد مساراً آخر؛ اضبط `LLM_MODEL_PATH` في `.env` على نفس المسار.

لتشغيل السيرفر بعد نجاح الاختبار باستخدام نفس النموذج المحمّل، بدون إعادة تجهيز الأوزان:

```powershell
python scripts/setup_llm.py --verify-only --serve --model-dir D:/AI/models/ASL-4B-v1
```

على CPU، يستخدم الحساب `bfloat16` عند توفر AVX512-BF16، وإلا يستخدم `float32` لتجنب حسابات BF16 البطيئة على معالجات AVX2. تظل الأوزان مضغوطة 4-bit عند تفعيل التكميم.

التشغيل الافتراضي عصبي محلي مع تكميم 4-bit. CPU قد يكون بطيئاً. إعدادات الجهاز والتكميم والمهلة وعدد الرموز في `.env.example`. لا ينزّل السيرفر أوزاناً، ولا يتحول تلقائياً إلى heuristic. تجنب عدة workers وreload أثناء الاستخدام كي لا تحمل الأوزان أكثر من مرة.

السيرفر يحمّل النموذج ويختبر التوليد عند بدء التشغيل. `/health` يفحص حياة السيرفر، و`/ready` يرجع HTTP 200 عند جاهزية قاعدة البيانات والـworkflow والنموذج والـRAG، أو HTTP 503 خلاف ذلك، مع عرض وضع التشغيل والجهاز والتكميم ونجاح التوليد.

`LLM_MODE=heuristic` وضع صريح للاختبارات والعرض الخفيف، ويظهر باسمه الحقيقي. pytest يستخدمه مع بيانات معزولة؛ لا يثبت سلوك النموذج العصبي. اختبار ASL الفعلي مستقل عبر setup.

---

## تجهيز RAG محلي

```powershell
python scripts/setup_rag.py --model-dir D:/AI/models/paraphrase-multilingual-MiniLM-L12-v2
```

اضبط `EMBEDDING_MODEL_PATH` في `.env` على نفس المسار. يستخدم إعداد RAG نسخة ثابتة من النموذج متعدد اللغات، يتحقق من بصمة الأوزان، ويبني FAISS بمتجهات مطبّعة ودرجات cosine حقيقية. ينفّذ 11 حالة قبول على النموذج الفعلي ويكتب `data/reports/rag-verification.json`. `--build-only` يعيد البناء من الملفات المحلية بدون تنزيل؛ استخدمه بعد تعديل الأدلة أو `knowledge/catalog.json`.

الفهرس يسترجع فقط أقسام الأدلة المسجلة في catalog. هذه مراجع المشروع وليست شهادات اعتماد من المصنع. عناوين الملفات وحدها لا تُفهرس. الفلترة حسب نوع الجهاز والأعراض، وعند وجود خطر تُسترجع إجراءات السلامة المطابقة فقط. `RAG_MIN_SCORE` و`RAG_TOP_K` يطبقان فعليًا. لا توجد نتيجة عامة بدرجة ثقة مصطنعة.

ASL يختار معرفات الإجراءات المناسبة، ثم تُعرض تعليمات المصدر نفسها بترتيبها. التوصية لا تحتوي خطوات حرة يولدها النموذج. الاختيارات غير الصحيحة أو التي تتجاهل عرضًا له مرجع مسترجع تُرفض. عند عدم وجود دليل، يُنشأ بلاغ للفحص الميداني بحالة توصية `manual_review` دون ادعاء إجراء موثق؛ والتغطية الجزئية تظهر بحالة `partial` مع توضيح الحاجة لفحص إضافي. مرجع التوصية يظهر في الواجهة.

تُحفظ نسخة الإجراء وبصمة المصدر وإصدار الفهرس مع التذكرة. يضيف بدء التشغيل عمودي `recommendation_status` و`recommendation_evidence` بدون تغيير بيانات التذاكر القديمة؛ تبقى القديمة `legacy` بدون مراجع مختلقة. `/ready` يشمل جاهزية RAG. الفهرس الناقص أو التالف أو الذي تغيرت مصادره يرجع عدم جاهزية، ولا يُستخدم لإنشاء توصية. كل بناء ينشر إصدارًا كاملًا بطريقة ذرية، ويحافظ على الإصدار السابق إذا فشل البناء. ملف `manifest.json` القديم لا يستخدمه المحرك الجديد.


## 🧪 تشغيل الاختبارات (Pytest)
```bash
pytest
```

---

## 📁 هيكلة المشروع (Architecture)

* `app/main.py`: مسارات `/api/maintenance/requests` و`/api/maintenance/requests/{thread_id}/continue`، والجاهزية.
* `app/config.py`: إعدادات النظام ومسارات البيانات ونموذج ASL-4B-v1.
* `app/schemas.py`: نماذج Pydantic الموحدة للـ API وحالة المسار.
* `app/db/database.py`: إدارة جداول SQLite والبحث عن الأجهزة وحفظ التذاكر.
* `app/rag/engine.py`: محرك الـ RAG، تقطيع أدلة الصيانة، والبحث بالتشابه الدلالي.
* `app/llm/client.py` و`app/llm/llama_cpp.py`: عميل ASL المحلي حسب `LLM_ENGINE`.
* `app/llm/agents.py`: وكيل الاستخراج (Extraction) ووكيل التوصية (Recommendation).
* `app/policies/rules.py`: قواعد الأولوية والسلامة الصارمة (كود بايثون 100%).
* `app/workflow/`: مسار العمل الكامل عبر LangGraph (`state.py`, `nodes.py`, `graph.py`).

## أزمنة الخطوات والتكامل

`duration_ms` في trace زمن مقاس بـperf_counter للخطوة المكتملة. الاستكمال يحتفظ بأزمنة السابق، ولا يشمل انتظار المستخدم أو كامل زمن HTTP. الجهاز يُراجع من SQLite وقت الاختيار، حتى لو تغيرت حالته أو موقعه أثناء الانتظار.

أخطاء النموذج ترجع 502 أو 503 حسب السبب برسائل آمنة، بدون تفاصيل SQL أو نجاح مختلق. `error_code` يميز `rag_unavailable` و`model_unavailable` و`invalid_model_output` و`processing_failed`.

اختبارات المتصفح تستخدم `tests/browser_server.py` بقاعدة مؤقتة ووضع heuristic ومتجهات مضبوطة معلنة. مسارات `/__test__` لا تُضاف إلى تطبيق الإنتاج. راجع [مصفوفة المشاكل الـ12 وأوامر التحقق](../docs/TESTING.md).
