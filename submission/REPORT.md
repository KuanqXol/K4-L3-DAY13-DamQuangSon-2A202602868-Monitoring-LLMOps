# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đàm Quang Sơn
- **MSSV:** 2A202602868
- **Lớp:** H202
- **Repository URL:** https://github.com/KuanqXol/K4-L3-DAY13-DamQuangSon-2A202602868-Monitoring-LLMOps
- **Commit SHA cuối:** Chưa chốt; sẽ điền sau commit cuối chứa toàn bộ CP2 source và evidence.
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602868`

**Trạng thái checkpoint:** CP2 đã hoàn thành về code và runtime. Các file `.txt` trace/prompt là API export thật từ project cá nhân; theo checklist nộp bài, vẫn cần chụp ảnh Langfuse `06`–`10` trước khi gọi là submission-ready. CP3 chưa chạy vì chưa có `config/challenge.json` chính thức do Lab Coach phát hành.

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | `evidence/06-trace-list.txt` |
| Trace waterfall | `evidence/07-trace-waterfall.txt` |
| Trace metadata | `evidence/08-trace-metadata.txt` |
| Prompt versions | `evidence/09-prompt-versions.txt` |
| Prompt rollback | `evidence/10-prompt-rollback.txt` |
| Dashboard runtime | `evidence/11-dashboard-overview.png`, `evidence/11-dashboard-overview.html` và `evidence/11-dashboard-overview.txt` |
| Incident metric | Chưa có evidence (CP3 chưa được mở) |
| Incident log | Chưa có evidence (CP3 chưa được mở) |
| Incident trace | Chưa có evidence (CP3 chưa được mở) |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Đạt tuyệt đối: đầy đủ correlation_id, log enrichment và PII scrubbing |
| `validate_dashboard.py` | 6/6 panel hợp lệ | 6/6 panel hợp lệ | Hợp lệ theo contract 6 panel |
| `pytest` | 22/22 passed | 25/25 passed | Toàn bộ tests hiện tại đều passed, gồm test child observations và prompt trace |
| Số traces hợp lệ | Chưa đo | 20 traces | 10 trace với prompt v1/baseline và 10 trace với prompt v2/candidate trong project cá nhân |
| Số PII leak | 0 | 0 | Không còn rò rỉ PII nguyên văn trong logs |
| Latency P95 / TTFT P95 | ~391ms / N/A | 1094ms / 51ms | Số liệu từ dashboard runtime trên cửa sổ 60 phút |
| Retrieval success rate | 100% | 100% | Retrieval thành công 100% trong load test |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:**
  - Trong `app/middleware.py`, tạo `CorrelationIdMiddleware(BaseHTTPMiddleware)`.
  - Ở đầu mỗi request, gọi `clear_contextvars()` để xóa contextvars cũ, tránh rò rỉ context giữa các request khác nhau.
  - Nhận `x-request-id` từ request header nếu client truyền lên; nếu không có, middleware tự sinh chuỗi ID mới với định dạng `req-<8-hex>` (`f"req-{uuid.uuid4().hex[:8]}"`).
  - Gắn ID vào structlog contextvars bằng `bind_contextvars(correlation_id=correlation_id)` và lưu vào `request.state.correlation_id`.
  - Khi hoàn thành request, middleware tính `duration_ms` và trả về hai header: `x-request-id` và `x-response-time-ms`.
  - `correlation_id` cũng được trả về trong response body (`ChatResponse.correlation_id`), truyền vào metadata của các log events (`request_received`, `response_sent`) và đưa vào metadata của trace Langfuse để liên kết log với trace.

- **Các metadata được ghi vào structured log:**
  - Metadata cơ bản toàn cục: `ts` (ISO 8601 UTC timestamp), `level` (`info`, `error`, `warning`), `service` (`api`, `control`, v.v.), `event` (`request_received`, `response_sent`, `request_failed`, `app_started`).
  - Metadata request context (được bind trước khi ghi log đầu tiên của request): `correlation_id`, `user_id_hash` (SHA256 băm 12 ký tự đầu để bảo vệ danh tính user), `session_id`, `feature`, `model` (`claude-sonnet-4-5`), `env` (`dev`).
  - Metadata payload và vận hành (`response_sent`): `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name` (`retrieval`), `tool_success` (`true`), `payload.answer_preview` (được tóm tắt và scrub).

- **Cách bảo đảm PII được scrub trước khi ghi:**
  - Xây dựng regex patterns trong `app/pii.py` cho 4 loại thông tin nhạy cảm: `email`, `phone_vn` (hỗ trợ các đầu số 09, 03, +84 và các phân cách space, dot, hyphen), `cccd` (12 chữ số), `credit_card` (16 chữ số liền nhau hoặc chia nhóm 4 số bởi space/hyphen).
  - Hàm `scrub_text` thay thế toàn bộ các chuỗi khớp mẫu bằng nhãn `[REDACTED_<TYPE>]`.
  - Trong `app/logging_config.py`, tạo processor `scrub_event` duyệt đệ quy toàn bộ các trường trong `event_dict` (trừ `ts` và `level`) để làm sạch chuỗi văn bản, dictionary con và list.
  - Đăng ký `scrub_event` TRƯỚC `JsonlFileProcessor` và `JSONRenderer` trong pipeline structlog processors, đảm bảo PII được che triệt để trước khi serialize JSON và trước khi ghi vào file `data/logs.jsonl` hoặc stdout.

- **Cách kiểm chứng kết quả:**
  - Chạy các test PII/validator trong bộ pytest hiện tại: toàn bộ test cases cho email, phone, CCCD, credit card và validator detection đều PASSED.
  - Khởi động server với `.env`, chạy `python scripts/load_test.py` với 10 sample queries (chứa email, phone, credit card).
  - Chạy `python scripts/validate_logs.py`: đạt điểm tuyệt đối **100/100** với 0 missing required fields, 0 missing enrichment fields, 20 unique correlation IDs và 0 PII leak detected.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** Chạy workload CP2 qua `scripts/run_cp2_workload.py` với key của project `day13-k4-l3a-2A202602868`; collector đọc 20 trace ID từ Langfuse v2 observations. API export nằm ở `evidence/06-trace-list.txt`; ảnh Langfuse theo checklist nộp bài còn cần chụp thủ công.
- **Cấu trúc root/retrieval/generation observations:** Root `lab-agent-run` (`AGENT`) có hai child cùng `parent_observation_id`: `retrieval` (`RETRIEVER`) và `llm-generation` (`GENERATION`). Waterfall mẫu nằm ở `evidence/07-trace-waterfall.txt`.
- **Cách nối trace với log:** `correlation_id` được truyền vào `propagate_attributes` và metadata của retrieval/generation/root; cùng ID xuất hiện trong `data/logs.jsonl`. Metadata mẫu: `evidence/08-trace-metadata.txt`.
- **Prompt name:** `day13-chat`.
- **Version/label baseline:** v1, label `baseline`; v1 cũng được gắn `production` ở trạng thái ổn định.
- **Version/label candidate:** v2, label `candidate`.
- **Trace ID của mỗi version:** v1/baseline: `757bb04cd361a79a1095065cdee537c4`, `2112a5be74d5b3f4a978cdd4c128fe27`, `d40d35ad6e9db5c790a065e81e6aeb6e`, `58dfe8637fa992ace766ad6bc4eefd60`, `bc261111ac0eab37ea90a6ea6683e62c`, `5abcad9e45114ed58119cc64d8e3ca9c`, `baf5e45201ad83ac47c0154770605801`, `470ca28497214fbb5b8d202089557898`, `31c0386862f208aeab571eb4f46bce6a`, `b4248d060e1f9a4955f6d92b213c67fd`. v2/candidate: `d4a32867615bcd7a2fb8d2f70c333465`, `c481ac051bf10f4f65b1a459bf41ba6d`, `04a0034c85de504bc08bab5c2b81aacf`, `9d0cc1f0cb414d1370ec4deaedf109a1`, `f5c95577f9a5c2454e697bb74f81fa03`, `8af18485ca51fffccc9de8650d692a2e`, `2075134600044047a3a2e1da2bdc86c7`, `dbd3b21680a693818032549fe607af06`, `115717cde72fbff365ad6c0dd15df511`, `ed3f0f05c15f7f4e2a25cb53c55a3fcc`.
- **Cách promote và rollback `production`:** Chạy `scripts/manage_prompts.py demonstrate-rollback`: trạng thái ban đầu v1=`baseline, production`, promote chuyển `production` sang v2, rollback đưa `production` về v1. Output thực tế nằm ở `evidence/10-prompt-rollback.txt`; danh sách version ở `evidence/09-prompt-versions.txt`. Hai file này là API output thật, chưa thay thế ảnh UI Langfuse nếu giảng viên áp dụng checklist ảnh nghiêm ngặt.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** `scripts/build_dashboard.py` tạo `dashboard/index.html` từ `data/logs.jsonl` và evidence runtime `evidence/11-dashboard-overview.html`. Sáu panel là latency/P50-P95-P99/TTFT, traffic, errors/retrieval success, cost, tokens và quality. Cửa sổ dữ liệu là 60 phút, refresh 30 giây.
- **SLO và lý do chọn:** `fast_successful_requests`, cửa sổ 28 ngày, target 99.5%; một request tốt là `response_sent` với `latency_ms <= 3000`. Ngưỡng phản ánh mục tiêu phản hồi nhanh nhưng vẫn phù hợp workload fake LLM.
- **Cách tính error budget:** `100 - 99.5 = 0.5%`; tương đương tối đa 5 request lỗi/chậm trên mỗi 1000 request trong ví dụ của lab. Guardrails bổ sung: error rate tối đa 2%, retrieval success tối thiểu 90%, quality trung bình tối thiểu 0.75 và daily cost tối đa 2.50 USD.
- **Ba alert và runbook tương ứng:** `user_visible_latency_breach` (P95 > 3000 ms trong 10 phút), `request_failures_or_retrieval_degradation` (error rate > 2% hoặc retrieval success < 90% trong 5 phút), `quality_or_cost_guardrail_breach` (quality < 0.75 hoặc daily cost > 2.50 USD trong 15 phút). Cả ba có severity, owner, Slack channel và hướng dẫn mitigation trong `config/alert_rules.yaml` và `docs/alerts.md`.

## 7. Điều tra challenge

- **Challenge ID:** Chưa có; Lab Coach chưa phát hành `config/challenge.json` chính thức cho CP3.
- **Khoảng thời gian điều tra:** Chưa áp dụng.
- **Triệu chứng từ metrics:** Chưa áp dụng; không tự tạo hoặc dùng challenge ngoài lớp.
- **Log line và correlation ID liên quan:** Chưa áp dụng.
- **Trace ID và span gây ảnh hưởng:** Chưa áp dụng.
- **Root cause:** Chưa kết luận khi chưa có challenge chính thức.
- **Fix action:** Chờ file challenge đúng lớp; sau đó chạy workload challenge và nối metric → log → trace.
- **Preventive measure:** Giữ nguyên quy trình điều tra theo thứ tự Metrics → Logs → Traces và không ghi evidence incident giả.

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** Tách retrieval và generation thành child observations bằng `start_as_current_observation` của Langfuse SDK v4; cách này giữ quan hệ cha-con và cho phép so sánh latency, token, cost theo từng bước.
- **Một lỗi/blocker đã gặp:** Collector ban đầu gọi `parse_io_as_json=true` và endpoint trace legacy. Langfuse trả HTTP 400/410 vì organization mới dùng observations API v2.
- **Cách tìm nguyên nhân và xử lý:** Đọc lỗi API, kiểm tra signature SDK v4.15.6, sau đó truy vấn `fields=core,basic,time,io,metadata,model,usage,prompt,metrics,trace_context`, dựng summary từ root observation và lọc metadata an toàn.
- **Cách hiểu luồng Metrics → Logs → Traces:** Dashboard xác định P95/error/retrieval bất thường; structured log cung cấp `correlation_id`; trace cùng ID cho biết retrieval hay generation là span gây ảnh hưởng.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:** Prompt version/label cho phép so sánh candidate với baseline và rollback nhanh; usage/cost cho biết tác động ngân sách; SLO/error budget quyết định khi nào ưu tiên reliability thay vì tiếp tục thay đổi prompt.
- **Điều quan trọng nhất đã học:** Validator xác nhận contract, còn evidence runtime mới chứng minh trace tree, prompt metadata và dashboard thực sự có dữ liệu.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:** CP3 chưa thể hoàn thành trước khi có challenge chính thức. Commit SHA cuối chưa chốt vì CP2 source/evidence hiện còn ở working tree; cần commit sau bước review cuối.

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối (chờ commit cuối).
- [x] Tất cả output CP2 hiện có mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace (CP3 chưa mở).
- [ ] Ảnh trace/prompt `06`–`10` từ giao diện Langfuse project cá nhân (hiện có API export thật, chưa có PNG UI).
- [x] Trace/prompt API export thuộc project Langfuse cá nhân và không lộ key/secret.
- [x] Repository chạy lại được theo README ở mức tests/validator/workload CP2.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác trong artifact đã tạo.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
