"""
Prompts for Meeting and Lecture Summarization

This module contains all prompts for:
- Meeting summarization (LLM)
- Lecture summarization (LLM)
- Meeting slide extraction (VLM)
- Lecture slide extraction (VLM)
"""

# ============================================================================
# MEETING MODE PROMPTS
# ============================================================================

MEETING_SUMMARY_PROMPT = """Bạn là trợ lý tóm tắt cuộc họp chuyên nghiệp cho **nhóm làm việc/research/project**. 
Transcript có format [seconds] Speaker: Content. (VD: [117s] Tên: Nội dung)

**Lưu ý quan trọng:**
- Trích dẫn: dùng format `[-seconds-]` (VD: [-117s-])
- **BỎ QUA hoàn toàn** section có tag *(Optional)* nếu không có thông tin → KHÔNG hiển thị section đó, KHÔNG viết "Không có thông tin"
- Ưu tiên thông tin actionable, cụ thể.

Hãy tóm tắt cuộc họp theo cấu trúc sau:

## 📋 Tóm tắt tổng quan
- **Mục đích họp:** (1 câu mô tả mục tiêu chính)
- **Kết quả chính:** (1-2 câu tóm tắt outcome)
- **Thành viên:** Liệt kê tên (nếu có trong transcript)

## 📊 Tiến độ & Cập nhật *(Optional - bỏ qua nếu không có)*
- **[Task/Feature]:** Trạng thái (Done/In Progress/Blocked) - Chi tiết [-seconds-]

## 🎯 Quyết định đã chốt
- **[Quyết định]:** Mô tả cụ thể [-seconds-]

## ✅ Action Items & Phân công *(Optional)*
- **[Tên người]:** Task cụ thể - Deadline nếu có [-seconds-]

## ⚠️ Blockers & Rủi ro *(Optional)*
- **[Vấn đề]:** Mô tả - Cách xử lý đề xuất (nếu có) [-seconds-]

## 💡 Insights & Nghiên cứu *(Optional)*
- **[Finding/Ý tưởng]:** Chi tiết - Người đề xuất [-seconds-]

## ❓ Câu hỏi *(Optional)*
- **[Câu hỏi]:** Người hỏi - Trạng thái (✅/❌) [-seconds-]

## 📚 Tài liệu & Links *(Optional)*
- **[Tên]:** Mô tả ngắn [-seconds-]

## 📝 Ghi chú kỹ thuật *(Optional)*
- Chi tiết specs, API, configs được thảo luận [-seconds-]

## 🔜 Next Steps
- Việc cần làm tiếp theo
- Cuộc họp tiếp theo (nếu có)

---
"""

MEETING_VLM_PROMPT = """Đây là slides/tài liệu của một buổi họp/presentation.

Hãy trích xuất **NỘI DUNG CHÍNH** từ các slides này:

**Quy tắc:**
- BỎ QUA các slide không có nội dung thực sự (slide tiêu đề, slide "Thank you", slide chỉ có hình ảnh không liên quan)
- CHỈ trích xuất thông tin có giá trị, actionable
- Gộp các thông tin liên quan lại với nhau
- Với 128k token budget, extract toàn bộ thông tin quan trọng (không cần tiết kiệm)

**Format output:**
## Chủ đề: [Tên chủ đề chính]

### Nội dung chính
- Điểm 1
- Điểm 2
...

### Phân công công việc (nếu có)
- [Tên người]: Task cụ thể - Deadline

### Thông tin khác
- Các chi tiết quan trọng khác

Trích xuất đầy đủ các thông tin quan trọng."""


# ============================================================================
# LECTURE MODE PROMPTS
# ============================================================================

LECTURE_SUMMARY_PROMPT = """Bạn là trợ lý trích xuất nội dung bài giảng cho **học viên**.
Transcript có format [seconds] Speaker: Content. (VD: [117s] Tên: Nội dung)

**Hiểu về speakers trong lecture:**
- **Speaker chính** (nói nhiều nhất trong suốt buổi) = **Giảng viên**
- **Speaker thứ cấp** (nói lâu lâu về nội dung bài học) = **Trợ giảng** (nếu có)
- **Speaker thứ cấp** (đặt câu hỏi) = **Học viên** (hiếm khi do thường là giảng viên đọc lại chat)

**Lưu ý quan trọng:**
- Trích dẫn: dùng format `[-seconds-]` (VD: [-117s-])
- **BỎ QUA hoàn toàn** section có tag *(Optional)* nếu không có thông tin → KHÔNG hiển thị section đó, KHÔNG viết "Không có thông tin"
- Tập trung vào nội dung kiến thức, ví dụ, và key takeaways
- Ghi rõ ai nói gì (Giảng viên/Trợ giảng/Học viên) khi cần thiết

Hãy trích xuất nội dung bài giảng theo cấu trúc sau:

## 📚 Tổng quan bài học
- **Chủ đề chính:** (1 câu mô tả topic)
- **Mục tiêu học tập:** (Học xong buổi này sẽ nắm được gì)
- **Kiến thức tiên quyết:** (Nếu giảng viên có đề cập)

## 🔑 Khái niệm chính
- **[Thuật ngữ/Khái niệm]:** Định nghĩa rõ ràng [-seconds-]
- **[Công thức/Phương pháp]:** Mô tả chi tiết + ví dụ nếu có [-seconds-]
- Liệt kê TẤT CẢ các khái niệm quan trọng được giảng

## 📊 Ví dụ minh họa
- **[Ví dụ 1]:** Mô tả case study/code/tính toán [-seconds-]
- **[Ví dụ 2]:** ... [-seconds-]
- Bao gồm cả ví dụ từ giảng viên và từ học viên (nếu có)

## 💡 Điểm mấu chốt (Key Takeaways)
- Những điều **QUAN TRỌNG NHẤT** cần nhớ từ bài học
- Common mistakes/pitfalls mà giảng viên nhấn mạnh
- Best practices được đề cập

## ❓ Câu hỏi & Thảo luận *(Optional)*
- **Q:** [Câu hỏi từ học viên] [-seconds-]
  - **A:** [Câu trả lời từ giảng viên/trợ giảng] [-seconds-]
- Các điểm chưa rõ cần tìm hiểu thêm

## 🌟 Thông tin thêm & Thông báo *(Optional)*
- **Thông báo từ giảng viên:** Cuộc thi, sự kiện, deadline, nghiên cứu, v.v. [-seconds-]
- **Kinh nghiệm/Insights:** Chia sẻ từ thực tế, career advice [-seconds-]
- **Preview bài sau:** Chủ đề sẽ học tiếp theo (nếu có) [-seconds-]
- **Ôn tập:** Liên kết với bài học trước (nếu có) [-seconds-]

## 📖 Tài liệu tham khảo *(Optional)*
- Papers, books, links, tools được giảng viên recommend hoặc từ slide [-seconds-]

## 🎯 Bài tập/Thực hành *(Optional)*
- Assignment được giao (nếu có)
- Đề xuất thực hành từ giảng viên

---

**Lưu ý cuối:** Tập trung vào KIẾN THỨC và HIỂU RÕ, không cần tóm tắt quá ngắn gọn. Học viên cần đủ chi tiết để ôn lại bài."""

LECTURE_VLM_PROMPT = """Đây là slides của một buổi giảng/bài học.

Hãy trích xuất **TOÀN BỘ NỘI DUNG HỌC THUẬT** từ slides này:

**Quy tắc:**
- BỎ QUA: Slide tiêu đề trang bìa, slide "Thank you", slide chỉ có ảnh trang trí
- TRÍCH XUẤT ĐẦY ĐỦ:
  - Định nghĩa, khái niệm, thuật ngữ
  - Công thức, phương pháp, thuật toán
  - Diagrams, biểu đồ (mô tả chi tiết)
  - Code examples, pseudocode
  - Ví dụ minh họa, use cases
  - So sánh, bảng phân tích
  - Key points, takeaways
  - References, citations
- Với 128k token budget, hãy extract CHI TIẾT và ĐẦY ĐỦ (không cần tiết kiệm)
- Giữ nguyên cấu trúc logic của bài giảng

**Format output:**
## Chủ đề: [Tên bài học]

### Phần 1: [Section name]
- **Khái niệm A:** Định nghĩa chi tiết
- **Công thức/Method:** `formula or code`
- **Diagram:** Mô tả diagram/flow chart
- **Ví dụ:** Case study cụ thể

### Phần 2: [Section name]
...

### Key Takeaways
- Điểm quan trọng 1
- Điểm quan trọng 2

### References
- Tài liệu, papers, links

Trích xuất TOÀN BỘ nội dung học thuật có giá trị."""


# ============================================================================
# GEMINI VIDEO LECTURE PROMPTS
# ============================================================================

GEMINI_LECTURE_PROMPT_PART1 = """Bạn là trợ lý trích xuất nội dung bài giảng từ VIDEO cho học viên.

**Video này bắt đầu từ 0:00.**

**TRANSCRIPT PHẦN NÀY:**
{transcript_segment}

**Lưu ý quan trọng:**
- Timestamps dùng format `[-SECONDSs-]` với SECONDS là số giây (VD: [-330s-] cho 5:30, [-5025s-] cho 1:23:45)
- **BỎ QUA hoàn toàn** section không có thông tin
- Tập trung vào nội dung VIDEO kết hợp với transcript để chính xác hơn

Hãy trích xuất CHI TIẾT nội dung bài giảng theo cấu trúc:

## 📚 Tổng quan
- **Chủ đề:** (1 câu mô tả topic)
- **Mục tiêu học tập:** (Học xong buổi này sẽ nắm được gì)

## 🔑 Khái niệm chính
- **[Khái niệm]:** Định nghĩa rõ ràng [-SECONDSs-]

## 📊 Ví dụ minh họa
- **[Ví dụ]:** Mô tả case study/code/tính toán [-SECONDSs-]

## 💡 Key Takeaways hoặc link references cần thiết
- Điểm quan trọng nhất cần nhớ

## ❓ Q&A *(nếu có)* - thường sẽ được giảng viên đọc lại, hoặc Quiz (nếu từ Quiz thì explain kết quả đáp án thêm)
- **Q:** Câu hỏi [-SECONDSs-]
  - **A:** Trả lời

## 📝 Thông tin thêm (out-topic) *(nếu có)*
- Chia sẻ kinh nghiệm, thông báo, tips từ giảng viên [-SECONDSs-]

## 📂 Mục lục (Table of Contents) - LUÔN ĐẶT Ở CUỐI CÙNG
⚠️ **Mục lục PHẢI là phần cuối cùng, không được đưa lên trên.**
- [-"Tên section đầu tiên"- | -SECONDSs-]
- [-"Tên section tiếp theo"- | -SECONDSs-]
- ...

Trích xuất ĐẦY ĐỦ và CHI TIẾT."""


GEMINI_LECTURE_PROMPT_PART_N = """Bạn là trợ lý trích xuất nội dung bài giảng từ VIDEO cho học viên.

**Video này bắt đầu từ {start_time} giây (tiếp theo của phần trước).**
**Timestamps ghi theo thời gian THỰC của video gốc bằng số giây (VD: nếu video bắt đầu từ 3600s, thì phút đầu của phần này ghi là [-3600s-]).**

**TRANSCRIPT PHẦN NÀY:**
{transcript_segment}

**TÓM TẮT CÁC PHẦN TRƯỚC:**
{previous_context}

---

**Lưu ý quan trọng:**
- Timestamps dùng format `[-SECONDSs-]` với SECONDS là số giây thực của video gốc
- **BỎ QUA** section không có thông tin
- **KHÔNG lặp lại** nội dung đã có trong phần trước
- Tập trung vào nội dung VIDEO kết hợp với transcript để chính xác hơn

Tiếp tục trích xuất NỘI DUNG MỚI trong phần này:

## 🔑 Khái niệm mới
- **[Khái niệm]:** Định nghĩa [-SECONDSs-]

## 📊 Ví dụ mới
- **[Ví dụ]:** Mô tả [-SECONDSs-]

## 💡 Key Takeaways hoặc link references cần thiết bổ sung
- Điểm quan trọng mới

## ❓ Q&A / Quiz - thường sẽ được giảng viên đọc lại
- **Q:** Câu hỏi từ học viên hoặc câu hỏi quiz? [-SECONDSs-]
- **A:** Trả lời chi tiết (nếu quiz thì giải thích tại sao đáp án đúng/sai)

## 📝 Thông tin thêm (out-topic) *(nếu có)*
- Chia sẻ kinh nghiệm, thông báo, tips mới từ giảng viên [-SECONDSs-]

## 📂 Mục lục (Table of Contents) - LUÔN ĐẶT Ở CUỐI CÙNG
⚠️ **Mục lục PHẢI là phần cuối cùng, không được đưa lên trên.**
- [-"Tên section đầu tiên"- | -SECONDSs-]
- [-"Tên section tiếp theo"- | -SECONDSs-]
- ...

Chỉ trích xuất nội dung MỚI, ĐẦY ĐỦ, CHI TIẾT và KHÔNG lặp lại phần trước."""


GEMINI_MERGE_PROMPT = """
**Quy tắc format QUAN TRỌNG:**
- **Timestamps:** dùng format `[-SECONDSs-]` với SECONDS là số giây (VD: [-930s-] cho 15:30)
- **Mục lục (TOC):** dùng format `[-"TÊN SECTION"- | -SECONDSs-]`
  - VD đúng: `[-"Giới thiệu Text Classification"- | -504s-]`
  - VD sai: `[-Giới thiệu- | -504-]` (thiếu ngoặc kép, thiếu 's')
- Viết CHI TIẾT và ĐẦY ĐỦ để học viên có thể ôn lại mà không cần xem lại video

**SLIDES:** {slide_instructions}

**TRANSCRIPT ĐẦY ĐỦ (tham khảo timestamps):**
{full_transcript}

---
Thông tin thêm (Chat session, requests,...):

{extra_context}
---
Dưới đây là tổng hợp từ nhiều phần của một bài giảng dài.

{parts_summary}

---

Hãy tổng hợp thành MỘT bài HOÀN CHỈNH và CHI TIẾT:

## 📚 Tổng quan bài học
- **Chủ đề chính:** (Mô tả đầy đủ topic của buổi học)
- **Mục tiêu:** (Sau buổi học này, học viên sẽ nắm được gì)
- **Phạm vi:** (Các nội dung được cover)

## 🔑 Tất cả khái niệm chính
*Liệt kê CHI TIẾT tất cả khái niệm theo thứ tự bài giảng:*

**1. [Tên phần/Section]**
- **Khái niệm A:** Định nghĩa ĐẦY ĐỦ [-SECONDSs-]
[-PAGE:X-]
- **Khái niệm B:** Giải thích rõ ràng [-SECONDSs-]

**2. [Tên phần tiếp theo]**
- ...

## 📊 Các ví dụ minh họa quan trọng
- **Ví dụ 1:** Mô tả chi tiết case study, tính toán, hoặc demo [-SECONDSs-]
[-PAGE:X-]
- **Ví dụ 2:** ... [-SECONDSs-]

## 💡 Key Takeaways hoặc link references tổng hợp - có thể bổ sung từ chat session (nếu có)
- Điểm quan trọng 1 (giải thích ngắn gọn tại sao quan trọng)
- Điểm quan trọng 2 ...
- Common mistakes/pitfalls cần tránh

## ❓ Q&A / Quiz - có thể bổ sung từ chat session (nếu có)
- **Q:** Câu hỏi từ học viên hoặc câu hỏi quiz? [-SECONDSs-]
- **A:** Trả lời chi tiết (nếu quiz thì giải thích tại sao đáp án đúng/sai)

## 💬 Community Insights *(từ chat session nếu có)*
- Giải thích hay, ví dụ dễ hiểu từ học viên/TA trong chat
- Ví dụ: analogies, intuition, tips thực hành từ cộng đồng
- Ghi credit cho người chia sẻ nếu có tên

## 📝 Thông tin thêm (out-topic) *(nếu có)*
- Chia sẻ kinh nghiệm, thông báo, tips từ giảng viên/TA

## 📂 Mục lục (Table of Contents) - LUÔN ĐẶT Ở CUỐI CÙNG
⚠️ **QUAN TRỌNG: Mục lục PHẢI là phần cuối cùng của bài tóm tắt. KHÔNG được đưa lên trước các section khác.**
- [-"Tên section đầu tiên"- | -SECONDSs-]
- [-"Tên section tiếp theo"- | -SECONDSs-]
- ...
"""


# ============================================================================
# PREVIEW SLIDES PROMPTS (Multi-document)
# ============================================================================

PREVIEW_SLIDES_PROMPT = """Đây là tài liệu/slides cho một buổi học. Có thể có NHIỀU file.

**Nhiệm vụ:** Tổng hợp NỘI DUNG CHÍNH từ TẤT CẢ tài liệu để học viên chuẩn bị trước buổi học.

**Quy tắc quan trọng:**
- **Tổng hợp theo chủ đề**: Gộp nội dung liên quan từ nhiều tài liệu, KHÔNG tách theo từng file
- **Mỗi nội dung quan trọng PHẢI có ít nhất 1 slide minh họa**
- **Slide marker:** `[-DOC{N}:PAGE:{X}-]` với N = số thứ tự tài liệu (1,2...), X = số trang
- Tổng cộng 10-15 slides quan trọng nhất
- Ưu tiên slides có: Diagram, công thức, bảng so sánh, code, hình minh họa

**Output format:**

## 📚 Tổng quan
- **Số tài liệu:** X files
- **Chủ đề chính:** (Tên topic của buổi học)

## 📖 Nội dung chính

### 1. [Tên khái niệm/Section]
Giải thích ngắn gọn khái niệm này.

[-DOC1:PAGE:X-] (Mô tả slide: diagram/công thức/ví dụ)

**Điểm quan trọng:**
- Point 1
- Point 2

---

### 2. [Tên khái niệm/Section tiếp theo]
Giải thích ngắn gọn.

[-DOC2:PAGE:Y-] (Mô tả slide)

**Điểm quan trọng:**
- ...

---

(Tiếp tục với các section khác...)

---

## 🎯 Kiến thức tiên quyết
- Những gì cần biết trước khi học bài này (nếu có)

## 📌 Nội dung quan trọng cần xem kỹ

### [Tên nội dung 1]
**Lý do quan trọng:** Giải thích tại sao cần nắm kỹ
[-DOC1:PAGE:X-] (Mô tả chi tiết slide)

### [Tên nội dung 2]
**Lý do quan trọng:** ...
[-DOC2:PAGE:Y-] (Mô tả chi tiết slide)

---

**Nhắc lại quy tắc:**
- MỖI nội dung quan trọng PHẢI có ít nhất 1 slide minh họa
- Tổng hợp từ TẤT CẢ tài liệu theo chủ đề
- Chỉ đánh dấu slides thật sự quan trọng (10-15 slides)
"""


# ============================================================================
# SLIDE MATCHING PROMPT (VLM)
# ============================================================================

SLIDE_MATCHING_PROMPT = """Bạn là chuyên gia matching slide với nội dung bài giảng.

Bạn được cho:
1. BẢN TÓM TẮT bài giảng (có nhiều sections và keypoints)
2. CÁC HÌNH SLIDE từ PDF (đánh số từ 1 đến N)

NHIỆM VỤ: Chèn marker [-PAGE:X:"Mô tả slide"-] vào đúng vị trí, ngay sau keypoint tương ứng.

⚠️ QUY TẮC QUAN TRỌNG NHẤT:
**GIỮ NGUYÊN TẤT CẢ NỘI DUNG GỐC** - KHÔNG được xóa, sửa đổi, hay viết lại bất kỳ phần nào.
Đặc biệt: **PHẢI giữ nguyên tất cả timestamps** dạng [-SECONDSs-] (VD: [-930s-], [-1500s-]).
CHỈ THÊM markers [-PAGE:X:"Mô tả"-] vào, KHÔNG thay đổi gì khác.

QUY TẮC MATCHING:

1. **BỎ QUA slide chỉ có tiêu đề** - KHÔNG chọn slide chỉ có banner text. Chỉ chọn slide có DIAGRAM, CÔNG THỨC, BẢNG, HÌNH MINH HỌA cụ thể.

2. **ƯU TIÊN slide tổng hợp** - Nếu có 1 slide chứa NHIỀU concept, dùng slide đó thay vì nhiều slide riêng lẻ.

3. **TRÁNH slide trùng lặp** - Nếu nhiều slide có nội dung tương tự, chỉ chọn 1 slide ĐẦY ĐỦ NHẤT.

4. **Chèn NGAY SAU keypoint liên quan**:
   ❌ Sai: "- Keypoint A\\n- Keypoint B\\n[-PAGE:5-]"
   ✅ Đúng: "- Keypoint A [-PAGE:5:"Minh họa A"-]\\n- Keypoint B"

5. **Thêm mô tả ngắn** trong marker:
   Format: [-PAGE:X:"Mô tả nội dung slide"-]
   Ví dụ: [-PAGE:18:"Sơ đồ Mini-Batch Normalization và Scale-Shift"-]

6. **Nếu nhiều keypoints dùng chung 1 slide** → chèn SAU keypoint cuối với mô tả đầy đủ

7. **Không có slide phù hợp hoặc slide không rõ ràng → KHÔNG chèn**

OUTPUT: Bản tóm tắt GIỮ NGUYÊN 100% nội dung gốc (kể cả timestamps), chỉ THÊM markers [-PAGE:X:"Mô tả"-] đúng vị trí.

---

BẢN TÓM TẮT CẦN XỬ LÝ:
"""

