# ملخّص اليوم الرابع (التقييم) — فريق 5

هدف اليوم الرابع: **تقييم** الوكيل الذي بنيناه في الأيام 1–3، دون إعادة بنائه. لا نغيّر منطق
التطبيق إلا عند الحاجة؛ نضيف ما يجعل سلوكه قابلاً للقياس. ما يلي كل تغيير ولماذا، بلغة مبسّطة.

## قبل البدء
- الفرع: `feature`. لم نرفع أي شيء إلى GitHub، ولم نُدرج `backend/.env` أو أي مفتاح في المستودع.
- لتفعيل تتبّع Phoenix (Day 4):
  ```bash
  cd fursah-starter/backend
  ..\..\.venv\Scripts\python.exe -m pip install -r requirements-observability.txt
  phoenix serve           # يفتح الواجهة على http://localhost:6006
  ```
  ثم في `backend/.env`:
  ```dotenv
  FURSAH_EVALUATION_TIME=2026-10-18T12:00:00+03:00
  FURSAH_PHOENIX_ENABLED=true
  FURSAH_PHOENIX_INSTRUMENT=langchain
  ```

## الجزء 0 — ملفات المدرّب
- ملفات اليوم الرابع من المدرّب (`evals/run_eval.py`, `evals/graders.py`, `evals/dev_cases.jsonl`,
  `observability.py`, `day4/`) **موجودة أصلاً** في الفرع (مُدمجة سابقاً). لم نعدّل
  `run_eval.py` إطلاقاً (ممنوع تعديله).
- احتفظنا بأداة التقييم القديمة التي كتبناها (٧ حالات) باسم `evals/smoke_eval.py` كفحص سريع
  بدون نموذج، وأزلنا منها فحص `execution_log` لأنه حُذف من الاستجابة. التقييم الرسمي هو
  `run_eval.py`.

## الجزء 2.1 — مراجعة قابلية التقييم (Audit)
في `day4/2.1-audit/audit_template.md` سجّلنا لكل مكوّن: مخرجاته، ونوع الفحص، والإشارة المفقودة.
- **نوع الفحص**: *حتمي (Deterministic)* إذا كان الفحص لا يحتاج سوى مدخلات المكوّن ومخرجاته
  (مثل: هل كل مُعرّف أعاده إعادة الترتيب موجود في القائمة؟). *قابل للتحقق (Verifiable)* إذا احتاج
  بيانات أو إجابات الحالات (مثل: هل الفرص المسترجعة مناسبة؟). *ذاتي (Subjective)* إذا احتاج
  حُكم نموذج (مثل: هل صياغة السبب جيدة؟) — وهذا فقط في `write_reason`.
- **الإشارة المفقودة** في كل صف هي ما سنسجّله كـ span في 2.2.

## الجزء 2.2 — التجهيز بالتتبّع (Instrument)
التنسيق عندنا يعمل بـ LangGraph، لكن نداءات النموذج تمرّ عبر `httpx` مباشرةً (ليست عبر LangChain).
لذلك: نضبط `FURSAH_PHOENIX_INSTRUMENT=langchain` (يلتقط تلقائياً مسارات الرسم البياني والعُقد)،
ونضيف الـ spans التي لا يراها هذا المُجهِّز يدوياً. كل بحث يُنتج **مسار (trace) واحد**:

| ما أضفناه | أين | ماذا يسجّل ولماذا |
|---|---|---|
| Span جذري `workflow.discover` | `workflow.discover` / `discover_all` | يجمع كل الخطوات في مسار واحد، ويسجّل `request_id` و`evaluation_time` لمطابقته مع سجل JSONL |
| Span نموذج `llm.<purpose>` | `agent.LlmClient.complete` | نوع LLM، المدخل والمخرج، وعدد الرموز (tokens)، واسم الدالة المستدعية (interpret_query / rerank / write_reason). span **واحد لكل نداء** وليس لكل محاولة إعادة |
| Span أداة `tool.search_opportunities` | `retrieve_node` | وسائط البحث، و`candidate_ids` و`candidate_source_ids` — لأن الحالات تُقيَّم بمعرّفات المصدر |
| Span `assess.filter` | `assess_node` | المصادر المُستبعَدة وسببها (منتهية/مغلقة/ملغاة)، وعدد المطابق مقابل القريب، والنتيجة |
| Span `rank.rerank` | `rank_node` | الترتيب الحتمي مقابل ترتيب النموذج، وهل استُخدم النموذج |

ملاحظة: هذه الـ spans **لا تفعل شيئاً** عندما يكون Phoenix مُعطّلاً، فلا تؤثر على التطبيق.
تحقّقنا بتشغيل بحث واحد (بدون مفتاح، أي بدون تكلفة) فظهرت كل الـ spans متداخلة بشكل صحيح تحت
`workflow.discover`.

## التشغيل والنتيجة الأساسية (Baseline)
```bash
cd fursah-starter/backend
..\..\.venv\Scripts\python.exe -m evals.run_eval --label baseline
```
شغّلناه بدون نموذج (بدون تكلفة) للتأكد من أن إضافاتنا على المخطّط (`approximate`, `BrowseResponse`,
وحذف `execution_log`) لا تكسر العقد: **لا يوجد PROTOCOL ERROR**. النتيجة الأساسية
`e2e.status = 0.67` (16 من 24).

**أهم ملاحظة لـ 2.4:** معظم الإخفاقات هي حالات `no_match` أعادت `ok`، لأن ميزة «إظهار الأقرب عند
عدم وجود مطابقة» التي أضفناها ترجع أقرب الفرص بدل `no_match`، بينما تتوقّع حالات اليوم الرابع
`no_match`. هذا تعارض بين الميزة والتقييم نحسمه في 2.4.

## المتبقّي
- **2.3**: كتابة المُقيّمات (graders) في `evals/graders.py` باستخدام الـ spans أعلاه، وحالة فريق واحدة.
- **2.4**: التشخيص والإصلاح (بدءاً من حالات `no_match`) ومقارنة قبل/بعد.
