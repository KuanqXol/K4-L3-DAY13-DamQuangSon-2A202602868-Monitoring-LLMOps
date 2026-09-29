# Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert 1 — User-visible latency breach

- Tên: `user_visible_latency_breach`
- Severity: `critical`
- Duration: `10m`
- Kênh thông báo: Slack
- SLI/SLO liên quan: `fast_successful_requests`, target 99.5%, latency threshold 3000 ms.
- Điều kiện và thời gian duy trì: P95 latency > 3000 ms liên tục trong 10 phút.
- Ảnh hưởng tới người dùng: câu trả lời chậm, timeout hoặc retry tăng.
- Ba bước kiểm tra đầu tiên: mở panel latency/TTFT; lọc structured log theo khoảng thời gian; mở trace có P95 cao và so sánh retrieval với generation.
- Mitigation tạm thời: giảm concurrency, tắt feature đang gây tail latency nếu có thể, giữ thông báo Slack cập nhật mỗi 15 phút.
- Owner: `llm-platform-oncall`

## Alert 2 — Request failures or retrieval degradation

- Tên: `request_failures_or_retrieval_degradation`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack
- SLI/SLO liên quan: error rate tối đa 2%, retrieval success tối thiểu 90%.
- Điều kiện và thời gian duy trì: error rate > 2% hoặc retrieval success < 90% liên tục trong 5 phút.
- Ảnh hưởng tới người dùng: request thất bại hoặc câu trả lời thiếu ngữ cảnh.
- Ba bước kiểm tra đầu tiên: xem panel errors; lấy `correlation_id` từ `request_failed`; mở trace và kiểm tra observation `retrieval`.
- Mitigation tạm thời: chuyển sang fallback answer, giảm traffic vào retrieval backend, khôi phục khi success rate ổn định.
- Owner: `api-oncall`

## Alert 3 — Quality or cost guardrail breach

- Tên: `quality_or_cost_guardrail_breach`
- Severity: `warning`
- Duration: `15m`
- Kênh thông báo: Slack
- SLI/SLO liên quan: quality proxy trung bình tối thiểu 0.75 và daily cost tối đa 2.50 USD.
- Điều kiện và thời gian duy trì: quality score < 0.75 hoặc daily cost > 2.50 USD liên tục trong 15 phút.
- Ảnh hưởng tới người dùng: câu trả lời kém hữu ích hoặc hệ thống có nguy cơ vượt ngân sách.
- Ba bước kiểm tra đầu tiên: so sánh panel quality với prompt label/version; kiểm tra tokens và cost theo trace; đối chiếu traffic để phân biệt tăng tải với tăng chi phí mỗi request.
- Mitigation tạm thời: rollback prompt về version đã kiểm chứng, giới hạn output tokens và giảm workload không thiết yếu.
- Owner: `llm-ops`
