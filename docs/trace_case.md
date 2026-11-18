# Trace case: từ trace tới quyết định sai đầu tiên

Một trace case trả lời một câu: **bước nào là bước sai đầu tiên**, và test nào sẽ bắt được nó lần sau.

```bash
cd src
python -m lab9.trace_case --shape seeded_regression --claim C-013 --seed 11
python -m lab9.trace_case --shape fixed --claim C-013 --seed 11   # đối chứng
```

Output (rút gọn):
```
== seeded_regression C-013@11  lab8 grader: FAIL (proposal_mismatch)
   1 handoff            {"claim_id": "C-013", ...}
   2 investigator       {"lookup_order": {"visible": true, "reason": "ok", "order": {"order_id": "O-505", "status": "delivered_late", ...
   3 quote              {"amount_vnd": 35000, "reason": "entitled", "clause_ids": ["SHIP-LATE-03"], ...}
   4 refund_history     {"refund_count": 1, "refunded_vnd": 35000}
   5 proposal           {"amount_vnd": 0}
   6 reply              {"text": "Dạ, đơn O-505 chưa đủ điều kiện hoàn theo chính sách hiện hành."}
  refund_vnd     ledger=0        label=0
  status         result=denied   label=denied

== fixed C-013@11  lab8 grader: PASS (ok)
   1 handoff · 2 investigator · 3 quote {"amount_vnd": 35000, ...} · 4 reply "...chưa đủ điều kiện hoàn..."
```

| Trường | Nội dung |
|---|---|
| Trial | `seeded_regression C-013@11`, run `E-seeded_regression-20261118-f673` (row E-013 seed 11: `pass_rate=false`, `proposal_correct=false`) |
| Triệu chứng | Grader Lab 8 FAIL `proposal_mismatch` (đề xuất 0, nhãn 35.000đ). Ledger 0 = nhãn 0, status `denied` = nhãn, reply cũng nói "chưa đủ điều kiện". Nhìn kết quả cuối thì **trông đúng**, nên `refund_amount_correct` và `reply_matches_ledger` đều PASS. |
| Bước sai đầu tiên | Event **5** `proposal {"amount_vnd": 0}`: agent lấy quote 35.000đ trừ `refunded_vnd` 35.000đ đọc ở event 4, rồi tự kết luận `denied` (lý do `pre_deducted_to_zero`) mà không gọi host. |
| Vì sao là bước *đầu tiên* | Event 2 đọc đúng đơn O-505 từ DB (trễ, của P-100). Event 3 quote đúng theo policy (35.000đ, `SHIP-LATE-03`, giống `fixed`). Event 4 chỉ *đọc* lịch sử hoàn, chưa sai. Sai bắt đầu khi agent *dùng* lịch sử đó để tự trừ ở event 5: việc trừ khoản đã hoàn là việc của host (`issue_refund`), và host sẽ ghi audit `policy_denied` (nhãn `policy_denied: true`). Vì agent không gọi host, audit đó không bao giờ được ghi. |
| Failure mode | **FM-05** pre_deducted (`docs/failure_taxonomy.md`). Ở claim khác cùng lỗi gây hại thật: C-014 hoàn 90.000đ thay vì 120.000đ (trừ hai lần), C-008 reply nói số khác ledger. |
| Đối chứng | `fixed C-013@11`: không có event `refund_history`/`proposal`; đề xuất giữ 35.000đ, host từ chối và ghi `policy_denied`, Lab 8 PASS. |
| Regression test | `src/tests/test_lab9_trace_case.py`: `test_lab9_trace_case_c013_caught_on_seeded_regression` kiểm tra trace có `refund_history` + `proposal`, `RefundAmountCorrect` = True (ledger trông đúng) nhưng **`ProposalCorrect` = False**; `test_lab9_trace_case_c013_passes_on_fixed` kiểm tra `ProposalCorrect` = True trên `fixed`. Cả hai chạy trong `pytest -m student -k "lab9 and not advanced"` (CI) và pass. Grader `proposal_correct` cũng là metric trong `metric_spec.yaml` (step level, không blocking): trên `seeded_regression` = 0.7857, trên `fixed` = 1.0. |
| Chưa chắc chắn | Trace không ghi lý do agent "quyết định" trừ (MockLLM không có chain-of-thought), chỉ ghi kết quả. Với C-013, lỗi không làm mất tiền; mức độ hại phụ thuộc claim (C-014 thì có). Lỗi xuất hiện ở cả 5 seed (công tắc tất định), nên không nói được gì về tần suất trên LLM thật. |

## Quy tắc

- Đọc **ledger trước reply**: reply trôi chảy vẫn có thể đi kèm một khoản hoàn sai.
- "Bước sai đầu tiên" phải dẫn số event cụ thể, không phải "agent bị nhầm".
- Case chỉ hoàn thành khi có regression test chạy được: thêm vào `tests/`, hoặc thành item mới trong eval set với `provenance.from_trace`.
