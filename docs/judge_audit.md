# Judge audit

Chạy: `python -m lab9.judge --csv <file> --audit 5` (backend replay, không cần key). FAIL là lớp dương (việc của judge là *tìm* lỗi).

| Tiêu chí | n | κ | Precision | Recall | Đạt FLOORS (κ≥0.6, P≥0.8, R≥0.7)? | Quyết định |
|---|---|---|---|---|---|---|
| tone_ok | 100 | 0.757 | 0.857 | 0.800 | **Đạt** (tp 24, fp 4, fn 6, tn 66) | **dùng** — chỉ cho giọng điệu, không bao giờ cho tiền/approval |
| helpful | 100 | 0.375 | 1.000 | 0.300 | **Không đạt** κ và R (tp 9, fp 0, fn 21, tn 70) | **loại** — không được làm gate |

Tỉ lệ lỗi hiệu chỉnh Rogan-Gladen:
- tone_ok: quan sát 0.28 → hiệu chỉnh 0.30 (sens 0.8, spec 66/70 = 0.943).
- helpful: quan sát **0.09** → hiệu chỉnh **0.30**. Judge báo 9% reply không hữu ích, thực tế khoảng 30%: judge che hơn 2/3 số lỗi.

## ≥5 case audit thủ công

| # | Case | Judge nói | Người nói | Ai đúng? | Ghi chú / sửa rubric |
|---|---|---|---|---|---|
| 1 | tone H-008 "Em đã hoàn tiền cho anh rồi nha, anh check giúp em." | PASS | FAIL | **Người** | Xưng "em", "nha" quá suồng sã với khách khiếu nại. Rubric thêm: *xưng hô phải là "LogiX" / "anh/chị"; "em/bạn/nha/nhé" ⇒ FAIL*, kèm 2 ví dụ few-shot. |
| 2 | tone H-017 "Dạ, bạn ơi LogiX đã hoàn 25.000đ ... rồi nha." | PASS | FAIL | **Người** | Cùng lỗi xưng hô ("bạn ơi"). Cùng sửa như #1; judge đang nhầm "thân thiện" với "đúng mực". |
| 3 | tone H-029 "Dạ, vui lòng chờ. ... không cần nhắn thêm." | PASS | FAIL | **Người** | Judge chỉ thấy từ lịch sự ở đầu câu. Rubric thêm: *câu mệnh lệnh / cấm khách liên hệ ("không cần nhắn thêm") ⇒ FAIL dù có "Dạ"*. |
| 4 | tone H-042 "Dạ, đơn O-808 đã hoàn 120.000đ. Tiền về trong 3–5 ngày ạ." | FAIL | PASS | **Người** | Judge phạt vì "thiếu xin lỗi". Rubric sửa: *xin lỗi không bắt buộc khi kết quả là hoàn tiền; ngắn mà đủ ý = PASS*. |
| 5 | tone H-051 "Dạ, LogiX đã refund 90.000đ ..." | FAIL | PASS | **Người** | Style guide CS LogiX cho phép "refund". Rubric thêm danh sách từ tiếng Anh được phép (refund, ship, voucher). |
| 6 | tone H-063 "...đã hoàn 20.000đ và sẽ hoàn thêm cho anh/chị ạ." | PASS | FAIL | **Người**, nhưng **không phải việc của tone judge** | Lỗi là *hứa ngoài kết quả hệ thống* (gần FM-08). Không sửa rubric tone; để grader code `reply_matches_ledger` bắt số tiền, thêm luật code "cấm 'sẽ hoàn thêm' khi ledger không có lệnh hoàn chờ". |
| 7 | tone H-081 "Dạ, đơn O-107 chưa đủ điều kiện hoàn ... ạ." | FAIL | PASS | **Judge** (theo ghi chú: người đọc nhầm ticket) | Sửa **nhãn người** thành FAIL, ghi lại vào bộ nhãn v2; nhắc lại rằng người chấm cũng có lỗi, nên mỗi nhãn bất đồng cần người thứ hai xem. |
| 8 | tone H-094 "Da, LogiX da hoan 40.000đ cho don O-341 ..." | PASS | FAIL | **Người** | Mất dấu tiếng Việt (dịch máy). Rubric thêm: *thiếu dấu tiếng Việt ⇒ FAIL*. |
| 9 | helpful HL-015 "Dạ, LogiX đã hoàn 55.000đ cho đơn O-112 ạ." (ledger 40.000đ) | PASS | FAIL | **Người** | Judge không thấy ledger nên không thể biết số sai. Đây là kiểu lỗi chiếm đa số trong 21 FN của helpful. **Không sửa bằng rubric**: chấm bằng code `reply_matches_ledger` (FM-08). |
| 10 | helpful HL-016 / HL-043 (reply dài, xin lỗi lặp lại, số tiền sai so với ledger) | PASS | FAIL | **Người** | Judge bị câu xin lỗi dài "mua chuộc" (verbosity bias). Rubric thêm: *độ dài và lời xin lỗi không cộng điểm; đánh giá chỉ trên việc khách có biết chính xác chuyện gì đã xảy ra*. |
| 11 | helpful HL-047 "Ok bạn, đơn O-515 xử lý rồi nhé." | PASS | FAIL | **Người** | Không nói kết quả là gì, không nói số tiền. Rubric thêm: *reply phải nêu trạng thái (hoàn/từ chối/cần thêm thông tin) và số tiền nếu có hoàn*. |

## Kết luận
- **tone_ok dùng được** làm metric (đạt cả 3 sàn), nhưng chỉ cho giọng điệu. 6/10 bất đồng là FN cùng một kiểu (xưng hô suồng sã, mệnh lệnh, mất dấu): sửa rubric như bảng trên rồi calibrate lại trên nhãn mới.
- **helpful bị loại**: P = 1.0 nhưng R = 0.3 và κ = 0.375 < 0.6. Ma trận nhầm lẫn tp 9 / fn 21: judge bỏ sót 21/30 reply không hữu ích. Precision cao không cứu được: một gate dùng judge này sẽ cho qua khoảng 70% lỗi, và tỉ lệ lỗi báo cáo (9%) thấp hơn tỉ lệ thật (~30% sau Rogan-Gladen) hơn 3 lần. Phần lớn FN là reply nói **sai số tiền so với ledger**: judge không đọc ledger nên không thể chấm tiêu chí này. Tiền phải chấm bằng code (`reply_matches_ledger`), không bằng judge.
- Rủi ro còn lại: judge chỉ được kiểm trên dữ liệu replay đã công khai (100 dòng mỗi tiêu chí); cần nhãn người mới để có held-out thật, và cần calibrate lại sau mỗi lần sửa rubric.
