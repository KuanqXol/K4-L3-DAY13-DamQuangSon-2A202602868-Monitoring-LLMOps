# Báo cáo cá nhân — K4-L3A Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Đàm Quang Sơn
- **MSSV:** 2A202602868
- **Lớp:** H202
- **Repository URL:** https://github.com/KuanqXol/K4-L3-DAY13-DamQuangSon-2A202602868-Monitoring-LLMOps
- **Commit SHA cuối:**
- **Challenge ID:**
- **Tên project Langfuse cá nhân:** `day13-k4-l3a-2A202602868`

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Pytest cuối | `evidence/01-pytest.txt` |
| Log validator | `evidence/02-log-validator.txt` |
| Dashboard validator | `evidence/03-dashboard-validator.txt` |
| Structured log | `evidence/04-structured-log.txt` |
| PII redaction | `evidence/05-pii-redaction.txt` |
| Trace list | Chưa có evidence (CP2 chưa hoàn thành) |
| Trace waterfall | Chưa có evidence (CP2 chưa hoàn thành) |
| Trace metadata | Chưa có evidence (CP2 chưa hoàn thành) |
| Prompt versions | Chưa có evidence (CP2 chưa hoàn thành) |
| Prompt rollback | Chưa có evidence (CP2 chưa hoàn thành) |
| Dashboard runtime | Chưa có evidence (CP2 chưa hoàn thành) |
| Incident metric | Chưa có evidence (CP3 chưa hoàn thành) |
| Incident log | Chưa có evidence (CP3 chưa hoàn thành) |
| Incident trace | Chưa có evidence (CP3 chưa hoàn thành) |

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 | 100/100 | Đạt tuyệt đối: đầy đủ correlation_id, log enrichment và PII scrubbing |
| `validate_dashboard.py` | 6/6 panel hợp lệ | 6/6 panel hợp lệ | Hợp lệ theo contract 6 panel |
| `pytest` | 22/22 passed | 24/24 passed | Toàn bộ unit tests và PII tests đều passed |
| Số traces hợp lệ | 10 traces | 10 traces | Đã gửi được 10 traces lên Langfuse từ load_test có correlation_id |
| Số PII leak | 0 | 0 | Không còn rò rỉ PII nguyên văn trong logs |
| Latency P95 / TTFT P95 | ~391ms / N/A | ~400ms / 51ms | P95 latency ổn định, đã đo TTFT trong log |
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
  - Chạy `pytest tests/test_pii.py` và `pytest tests/test_validate_logs.py`: toàn bộ test cases cho email, phone, cccd, credit card và validator detection đều PASSED (24/24).
  - Khởi động server với `.env`, chạy `python scripts/load_test.py` với 10 sample queries (chứa email, phone, credit card).
  - Chạy `python scripts/validate_logs.py`: đạt điểm tuyệt đối **100/100** với 0 missing required fields, 0 missing enrichment fields, 10 unique correlation IDs và 0 PII leak detected.

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:**
- **Cấu trúc root/retrieval/generation observations:**
- **Cách nối trace với log:**
- **Prompt name:**
- **Version/label baseline:**
- **Version/label candidate:**
- **Trace ID của mỗi version:**
- **Cách promote và rollback `production`:**

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:**
- **SLO và lý do chọn:**
- **Cách tính error budget:**
- **Ba alert và runbook tương ứng:**

## 7. Điều tra challenge

- **Challenge ID:**
- **Khoảng thời gian điều tra:**
- **Triệu chứng từ metrics:**
- **Log line và correlation ID liên quan:**
- **Trace ID và span gây ảnh hưởng:**
- **Root cause:**
- **Fix action:**
- **Preventive measure:**

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:**
- **Một lỗi/blocker đã gặp:**
- **Cách tìm nguyên nhân và xử lý:**
- **Cách hiểu luồng Metrics → Logs → Traces:**
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
- **Điều quan trọng nhất đã học:**
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**

## 9. Checklist trước khi nộp

- [ ] Kết quả và evidence thuộc commit SHA cuối.
- [ ] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [ ] Incident evidence nối đúng metric → log → trace.
- [ ] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [ ] Repository chạy lại được theo README.
- [ ] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
