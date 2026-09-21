import os
from dataclasses import dataclass

from google import genai
from google.genai import types as genai_types
from dotenv import load_dotenv

load_dotenv()

@dataclass
class DeviceInfo:
    brand: str
    model_name: str


def _get_client():
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def _generate(client, prompt: str, max_output_tokens: int = 800, temperature: float = 0.4) -> str | None:

   
    response = client.models.generate_content(
        model="gemini-3.5-flash",
        contents=prompt,
        config=genai_types.GenerateContentConfig(
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            thinking_config=genai_types.ThinkingConfig(
                thinking_level=genai_types.ThinkingLevel.MINIMAL,
            ),
        ),
    )
    if response and getattr(response, "text", None):
        text = response.text.strip()
        candidates = getattr(response, "candidates", None)
        if candidates and getattr(candidates[0], "finish_reason", None) == "MAX_TOKENS":
            print(f"[ai_service] CẢNH BÁO: phản hồi vẫn bị cắt do MAX_TOKENS (giới hạn={max_output_tokens}).")
        return text
    return None

# ==========================================
# 1. GIẢI THÍCH DỊCH VỤ SỬA CHỮA (dùng cho cả khách hàng lúc tiếp nhận máy
#    lẫn kỹ thuật viên/khách hàng xem lại trên phiếu)
# ==========================================
def explain_service(issue_description: str, technical_notes: str = "") -> str:
    if not issue_description:
        return "Vui lòng mô tả chi tiết lỗi bạn đang gặp phải."

    client = _get_client()
    if client is not None:
        try:
            context = f"Mô tả lỗi (khách hàng/kỹ thuật viên cung cấp): {issue_description}"
            if technical_notes:
                context += f"\nGhi chú/kết quả kiểm tra thực tế của kỹ thuật viên: {technical_notes}"

            prompt = (
                "Bạn là kỹ thuật viên trưởng chuyên sửa chữa điện thoại tại trung tâm "
                "KhanhThien SmartPhone. CHỈ dựa vào thông tin dưới đây, KHÔNG suy diễn "
                "thêm lỗi nào khác không được nhắc tới. Nếu có ghi chú thực tế của kỹ "
                "thuật viên thì ưu tiên ghi chú đó hơn mô tả ban đầu (vì đó là quan sát "
                "trực tiếp trên máy). Trả lời đúng 3 mục, ngắn gọn, dễ hiểu cho khách "
                "hàng không rành kỹ thuật:\n"
                "1. Lỗi dự đoán (Nguyên nhân chính):\n"
                "2. Hướng khắc phục đề xuất:\n"
                "3. Linh kiện dự kiến cần thay thế:\n\n" + context
            )
            result = _generate(client, prompt)
            if result:
                return result
        except Exception as e:
            print("LỖI GIẢI THÍCH AI:", str(e))  # rơi xuống bản dự phòng bên dưới

    return _explain_service_fallback(issue_description, technical_notes)


def _explain_service_fallback(issue_description: str, technical_notes: str = "") -> str:
    """Bản dự phòng khi chưa cấu hình GEMINI_API_KEY hoặc gọi API lỗi — dò
    theo từ khóa. KHÔNG dùng làm nguồn chính nữa (xem `explain_service`)."""
    text = issue_description.lower()

    if any(kw in text for kw in ["nước", "ướt", "bồn", "mưa", "chảy", "cầu thang", "sấy"]):
        nguyen_nhan = "Oxy hóa mạch điện, chạm chập IC nguồn hoặc bo mạch chính (Mainboard) do chất lỏng xâm nhập."
        khac_phuc = "Vệ sinh siêu âm bo mạch bằng hóa chất chuyên dụng, sấy khô và đo đạc cách ly tụ/IC bị chập."
        linh_kien = "IC Nguồn, tụ điện bị chập trên Main, hoặc cụm chân sạc."
    elif any(kw in text for kw in ["rơi", "rớt", "đất", "xe cán", "va đập", "móp", "cong"]) and any(kw in text for kw in ["không lên", "tắt", "mất nguồn", "ngủ"]):
        nguyen_nhan = "Hở chân chip/CPU, đứt đường mạch ngầm hoặc bung cáp nối nguồn/pin do lực chấn động mạnh."
        khac_phuc = "Tháo máy kiểm tra toàn bộ socket kết nối, đo kiểm tra trở kháng bo mạch, làm lại chân BGA nếu hở chip."
        linh_kien = "Sửa chữa Mainboard (chân chip/IC), cố định lại socket."
    elif any(kw in text for kw in ["màn", "kính", "sọc", "vỡ", "bể", "đốm", "cảm ứng", "tối đen", "chảy mực", "liệt"]):
        if any(kw in text for kw in ["kính", "bể mặt", "nứt kính"]) and not any(kw in text for kw in ["sọc", "mực", "tối", "liệt", "đốm"]):
            nguyen_nhan = "Nứt/vỡ mặt kính bảo vệ bên ngoài, phôi màn hình hiển thị và cảm ứng bên trong vẫn hoạt động bình thường."
            khac_phuc = "Tách kính vỡ bằng máy nhiệt và ép lại mặt kính mới bằng công nghệ chân không."
            linh_kien = "Mặt kính ngoại quan mới."
        else:
            nguyen_nhan = "Hỏng phôi màn hình OLED/LCD, đứt cổ cáp hiển thị hoặc chết IC cảm ứng."
            khac_phuc = "Kiểm tra cáp hiển thị. Thay thế trọn bộ cụm màn hình mới."
            linh_kien = "Cụm màn hình hiển thị nguyên bộ."
    elif any(kw in text for kw in ["pin", "sạc", "nóng", "sập", "phồng", "hao", "không vào"]):
        if any(kw in text for kw in ["phồng", "chai", "hao", "tụt"]):
            nguyen_nhan = "Pin đã suy giảm dung lượng (chai pin), phồng Cell pin gây nguy cơ đẩy hở màn hình."
            khac_phuc = "Đo kiểm tra số lần sạc và độ chai pin, tiến hành thay khối pin chuẩn mới."
            linh_kien = "Pin dung lượng chuẩn mới."
        else:
            nguyen_nhan = "Chân sạc hỏng/bụi bám, lỗi IC quản lý sạc (Tristar/Hydra) hoặc đứt cáp sạc."
            khac_phuc = "Vệ sinh/đo chân sạc, thử cáp sạc mới, kiểm tra đường đi dòng điện trên bo mạch."
            linh_kien = "Cụm cáp chân sạc hoặc IC Sạc trên Main."
    elif any(kw in text for kw in ["cam", "camera", "mờ", "rung", "không bật được", "máy ảnh", "đen"]):
        nguyen_nhan = "Hỏng cụm chống rung quang học (OIS) do va đập, đứt cáp camera hoặc lỗi IC Camera."
        khac_phuc = "Vệ sinh thấu kính, kiểm tra chân cắm socket camera, thay thế module camera hỏng."
        linh_kien = "Module Camera (Trước/Sau)."
    elif any(kw in text for kw in ["loa", "mic", "rè", "âm thanh", "mất tiếng", "không nghe", "nhỏ"]):
        nguyen_nhan = "Bụi bẩn làm nghẽn màng loa, rách màng loa hoặc lỗi IC Audio truyền dẫn âm thanh."
        khac_phuc = "Vệ sinh lưới loa bằng dung dịch chuyên dụng, thay thế cụm loa hoặc đóng lại IC Audio."
        linh_kien = "Loa trong, Loa ngoài (Chuông) hoặc IC Audio."
    elif any(kw in text for kw in ["sim", "sóng", "wifi", "bắt kém", "dịch vụ", "bluetooth", "mạng"]):
        nguyen_nhan = "Gãy khay SIM, hỏng IC Baseband (sóng) hoặc đứt dây ăng-ten thu phát sóng."
        khac_phuc = "Kiểm tra khay SIM, dán lại ăng-ten thu sóng, kiểm tra mạch công suất sóng trên main."
        linh_kien = "Khay SIM, Dây Ăng-ten sóng hoặc IC Baseband."
    elif any(kw in text for kw in ["treo", "logo", "đầy bộ nhớ", "lag", "chậm", "chạy lại", "vòng lặp"]):
        nguyen_nhan = "Xung đột phần mềm hệ thống, đầy bộ nhớ chip NAND Flash hoặc lỗi Firmware khi cập nhật."
        khac_phuc = "Khôi phục cài đặt gốc (Restore Firmware) qua phần mềm máy tính chuyên dụng."
        linh_kien = "Không cần thay linh kiện (Chạy lại phần mềm hệ thống)."
    elif any(kw in text for kw in ["rơi", "rớt", "đất", "va đập", "móp", "cong"]):
        nguyen_nhan = "Tác động lực cơ học làm lỏng linh kiện bên trong, biến dạng khung vỏ hoặc hở mạch nhẹ."
        khac_phuc = "Tháo máy kiểm tra lại toàn bộ các nẹp cố định, socket cắm và nắn lại khung vỏ."
        linh_kien = "Khung vỏ mới hoặc nắn lại vỏ cũ."
    else:
        nguyen_nhan = "Lỗi vi mạch phức tạp trên Mainboard hoặc sự cố xung đột giữa các linh kiện ẩn."
        khac_phuc = "Sử dụng kính hiển vi soi mạch và đồng hồ đo dòng để phát hiện tụ chập hoặc IC bị hỏng."
        linh_kien = "Chưa xác định (Cần kỹ thuật viên kiểm tra trực tiếp tại cửa hàng)."

    result = (
        f"1. Lỗi dự đoán (Nguyên nhân chính):\n- {nguyen_nhan}\n\n"
        f"2. Hướng khắc phục đề xuất:\n- {khac_phuc}\n\n"
        f"3. Linh kiện dự kiến cần thay thế:\n- {linh_kien}"
    )
    if technical_notes:
        result += f"\n\n4. Ghi chú kỹ thuật mới nhất:\n- {technical_notes}"
    return result


# ==========================================
# 2. TÓM TẮT TÌNH TRẠNG MÁY (cho kỹ thuật viên)
# ==========================================
def summarize_device_condition(issue_description: str, technical_notes: str = "") -> str:
    if not issue_description and not technical_notes:
        return "Chưa có mô tả lỗi hoặc ghi chú kỹ thuật nào để tóm tắt."

    combined = f"Mô tả lỗi ban đầu (lúc tiếp nhận máy): {issue_description or 'Không có'}\n"
    combined += f"Ghi chú kỹ thuật (cập nhật trong quá trình sửa): {technical_notes or 'Chưa có ghi chú mới'}"

    client = _get_client()
    if client is not None:
        try:
            prompt = (
                "Bạn là kỹ thuật viên trưởng của trung tâm sửa chữa điện thoại KhanhThien SmartPhone. "
                "Dựa vào thông tin dưới đây, hãy TÓM TẮT tình trạng hiện tại của máy trong 3-5 câu, "
                "bằng ngôn ngữ dễ hiểu (không dùng thuật ngữ khó), để lưu hồ sơ phiếu sửa chữa và "
                "có thể chia sẻ lại với khách hàng:\n\n" + combined
            )
            result = _generate(client, prompt, max_output_tokens=450)
            if result:
                return result
        except Exception as e:
            print("LỖI TÓM TẮT AI:", str(e))

    fallback = _explain_service_fallback(issue_description, technical_notes)
    return fallback


# ==========================================
# 3. TIN NHẮN CẬP NHẬT TIẾN ĐỘ CHO KHÁCH
# ==========================================
def generate_progress_message(
    customer_name: str,
    device: DeviceInfo,
    status_display: str,
    notes: str,
    issue_description: str = "",
    ai_summary: str = "",
) -> str:
    client = _get_client()
    if client is not None:
        try:
            context = (
                f"Tên khách hàng: {customer_name}\n"
                f"Thiết bị: {device.brand} {device.model_name}\n"
                f"Trạng thái hiện tại của phiếu: {status_display}\n"
            )
            if issue_description:
                context += f"Lỗi khách hàng báo ban đầu: {issue_description}\n"
            if ai_summary:
                context += f"Tóm tắt tình trạng máy (kỹ thuật viên đã ghi nhận): {ai_summary}\n"
            if notes:
                context += f"Ghi chú/công việc mới nhất kỹ thuật viên vừa cập nhật: {notes}\n"

            prompt = (
                "Bạn là kỹ thuật viên của trung tâm sửa chữa điện thoại KhanhThien SmartPhone. "
                "Hãy soạn MỘT tin nhắn ngắn gọn (3-5 câu), giọng văn thân thiện, chuyên nghiệp, "
                "gửi TRỰC TIẾP cho khách hàng để cập nhật tiến độ sửa máy. "
                "CHỈ dùng đúng thông tin dưới đây, không bịa thêm chi tiết không có trong dữ liệu. "
                "Nếu có ghi chú kỹ thuật thì hãy diễn đạt lại cho khách dễ hiểu (đừng copy nguyên "
                "văn thuật ngữ kỹ thuật), và nêu rõ hiện máy đang ở bước nào / dự kiến ra sao dựa "
                "theo trạng thái phiếu:\n\n" + context
            )
            result = _generate(client, prompt, max_output_tokens=400, temperature=0.5)
            if result:
                return result
        except Exception as e:
            print("LỖI TẠO TIN NHẮN TIẾN ĐỘ:", str(e))

    # Bản dự phòng (không cần API ngoài) khi chưa cấu hình GEMINI_API_KEY hoặc gọi lỗi.
    note_text = f" Ghi chú từ kỹ thuật viên: {notes}" if notes else ""
    return (
        f"Xin chào {customer_name}, thiết bị {device.brand} {device.model_name} của bạn hiện "
        f"đang ở trạng thái: {status_display}.{note_text} Cảm ơn bạn đã tin tưởng dịch vụ của chúng tôi!"
    )


# ==========================================
# 4. CHAT VỚI AI (khung chat)
# ==========================================
def chat_with_ai(user_message: str) -> str:
    try:
        client = _get_client()
        if client is None:
            return "Chưa cấu hình GEMINI_API_KEY trong file .env!"

        prompt = (
            "Bạn là kỹ thuật viên tư vấn sửa chữa điện thoại chuyên nghiệp của cửa hàng KhanhThien SmartPhone. "
            f"Khách hàng hỏi: '{user_message}'. "
            "Hãy trả lời ngắn gọn, lịch sự, tư vấn đúng trọng tâm nguyên nhân và hướng khắc phục."
        )
        result = _generate(client, prompt, max_output_tokens=400, temperature=0.6)
        return result or "Xin lỗi, hệ thống chưa thể trả lời lúc này, vui lòng thử lại."
    except Exception as e:
        print("LỖI CHI TIẾT:", str(e))
        return f"Xin lỗi, hệ thống gặp lỗi: {str(e)}"


# ==========================================
# 5. BÁO CÁO TỔNG QUAN CHO ADMIN/QUẢN LÝ
# ==========================================
def generate_admin_insight_report(
    status_counts: dict,
    total_revenue,
    top_issue_categories: list,
    top_used_parts: list,
    low_stock_parts: list,
) -> str:
    if not any([status_counts, top_issue_categories, top_used_parts]):
        return "Chưa có đủ dữ liệu vận hành để AI tổng hợp báo cáo."

    status_lines = "\n".join(
        f"- {label}: {count} phiếu" for label, count in status_counts.items()
    ) or "- Chưa có phiếu sửa chữa nào"

    issue_lines = "\n".join(
        f"- {label}: {count} lượt" for label, count in top_issue_categories
    ) or "- Chưa có dữ liệu"

    parts_lines = "\n".join(
        f"- {name}: {qty} cái" for name, qty in top_used_parts
    ) or "- Chưa có dữ liệu"

    low_stock_lines = "\n".join(f"- {name}" for name in low_stock_parts) or (
        "- Không có linh kiện nào sắp hết hàng"
    )

    combined = (
        f"Số phiếu sửa chữa theo trạng thái:\n{status_lines}\n\n"
        f"Tổng doanh thu (phiếu đã hoàn thành/đã giao khách): "
        f"{total_revenue:,.0f} VNĐ\n\n"
        f"Nhóm lỗi/linh kiện được thay nhiều nhất (proxy cho lỗi phổ biến):\n"
        f"{issue_lines}\n\n"
        f"Linh kiện dùng nhiều nhất:\n{parts_lines}\n\n"
        f"Linh kiện sắp hết hàng:\n{low_stock_lines}"
    )

    client = _get_client()
    if client is not None:
        try:
            prompt = (
                "Bạn là trợ lý phân tích vận hành cho chủ cửa hàng sửa chữa "
                "điện thoại KhanhThien SmartPhone. Dựa vào số liệu dưới đây, "
                "hãy viết một báo cáo ngắn gọn (5-7 câu) bằng tiếng Việt, "
                "giọng văn chuyên nghiệp, gồm 3 phần: "
                "1) Nhận xét tổng quan tình hình vận hành; "
                "2) Cảnh báo cụ thể nếu có linh kiện sắp hết hàng; "
                "3) Đề xuất hành động ưu tiên cho Quản lý trong tuần tới.\n\n"
                + combined
            )
            result = _generate(client, prompt, max_output_tokens=500)
            if result:
                return result
        except Exception as e:
            print("LỖI BÁO CÁO AI ADMIN:", str(e))

    fallback_lines = [
        "1. Tổng quan trạng thái phiếu sửa chữa:",
        status_lines,
        "",
        f"2. Doanh thu (phiếu đã hoàn thành/đã giao khách): "
        f"{total_revenue:,.0f} VNĐ",
        "",
        "3. Nhóm lỗi/linh kiện thay nhiều nhất:",
        issue_lines,
        "",
        "4. Linh kiện dùng nhiều nhất:",
        parts_lines,
        "",
        "5. Cảnh báo tồn kho (linh kiện sắp hết hàng):",
        low_stock_lines,
    ]
    return "\n".join(fallback_lines)


# ==========================================
# 6. TRỢ LÝ AI QUẢN LÝ (khung chat riêng cho Quản lý/Admin)
# ==========================================
def generate_admin_chat_response(question: str, data_context: str) -> str:
    """Viết phần NHẬN XÉT/ĐỀ XUẤT cho "Trợ lý AI Quản lý".

    QUAN TRỌNG: hàm này KHÔNG tự tính số liệu — toàn bộ số liệu trong
    `data_context` đã được `admin_ai_service.py` tính sẵn bằng Django ORM +
    Python. Gemini chỉ được phép diễn giải/nhận xét/đề xuất dựa đúng trên
    phần dữ liệu được cung cấp, không được bịa thêm hay suy đoán số liệu
    khác. Nếu chưa cấu hình GEMINI_API_KEY hoặc gọi API lỗi, trả về một câu
    thông báo trung lập — KHÔNG bịa nhận xét không có căn cứ.
    """
    client = _get_client()
    if client is not None:
        try:
            prompt = (
                "Bạn là \"Trợ lý AI Quản lý\" của trung tâm sửa chữa điện thoại "
                "KhanhThien SmartPhone. Bạn CHỈ phục vụ Quản lý/Admin cửa hàng, "
                "không phục vụ khách hàng, lễ tân, kỹ thuật viên hay thu ngân. "
                "Bạn CHỈ được dùng đúng số liệu do hệ thống cung cấp bên dưới, "
                "TUYỆT ĐỐI không được bịa thêm hoặc suy đoán số liệu không có "
                "trong đó. Nếu số liệu cho thấy chưa đủ dữ liệu để kết luận, "
                "hãy nói rõ điều đó thay vì đoán. Bạn không có quyền tự "
                "tạo/xóa/sửa phiếu, đổi trạng thái, nhập hàng hay thay đổi giá "
                "— bạn chỉ đưa ra thông tin, phân tích, cảnh báo và đề xuất. "
                "Giọng văn tiếng Việt, chuyên nghiệp, ngắn gọn (2-4 câu), dễ "
                "hiểu cho người quản lý cửa hàng.\n\n"
                f"Câu hỏi của Quản lý: {question}\n\n"
                f"Số liệu hệ thống đã tính sẵn (nguồn duy nhất được dùng):\n"
                f"{data_context}\n\n"
                "Hãy viết phần nhận xét ngắn gọn (và đề xuất nếu phù hợp) dựa "
                "đúng trên số liệu trên."
            )
            result = _generate(client, prompt, max_output_tokens=350, temperature=0.4)
            if result:
                return result
        except Exception as e:
            print("LỖI CHAT AI QUẢN LÝ:", str(e))

    return (
        "(Chưa thể tạo nhận xét tự động từ AI lúc này — số liệu phía trên "
        "vẫn là dữ liệu thật lấy từ hệ thống.)"
    )