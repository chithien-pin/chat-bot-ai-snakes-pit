"""
Ma trận test case theo kịch bản nghiệp vụ CellphoneS bot.
Mỗi case: phân loại kịch bản + bóc từ khóa (local, không LLM).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScenarioCase:
    id: str
    group: str
    query: str
    scenarios: tuple[str, ...]
    keywords_contains: tuple[str, ...] = ()
    keywords_exact: str = ""
    keywords_is_filter_url: bool = False
    compare_parts: tuple[str, ...] = ()
    scenarios_exclude: tuple[str, ...] = ()


SCENARIO_MATRIX: tuple[ScenarioCase, ...] = (
    # --- Tra cứu giá và khuyến mãi ---
    ScenarioCase(
        "price_01", "Tra cứu giá",
        "Giá ip 16 pro max 256gb titan tự nhiên hôm nay bao nhiêu",
        ("price_promotion",),
        ("iphone", "16", "pro max", "256"),
    ),
    ScenarioCase(
        "price_02", "Tra cứu giá",
        "Check giá s24 ultra 512gb",
        ("price_promotion",),
        ("s24", "ultra", "512"),
    ),
    ScenarioCase(
        "price_03", "Giá sau ưu đãi",
        "Iphone 16 thường 128gb giảm qua Kredivo còn bao nhiêu",
        ("price_promotion", "installment"),
        ("iphone", "16", "128"),
    ),
    ScenarioCase(
        "price_04", "Giá sau ưu đãi",
        "Check giá Mac Air M3 quẹt thẻ VIB được giảm thêm không",
        ("price_promotion", "installment"),
        ("mac", "m3"),
    ),
    ScenarioCase(
        "price_05", "Giá sau ưu đãi",
        "Mã Oppo Reno 15 F có chương trình giảm giá qua VNPay không",
        ("price_promotion", "installment"),
        ("oppo", "reno"),
    ),
    ScenarioCase(
        "price_06", "Giá sau ưu đãi",
        "Tủ lạnh Xiaomi có voucher gì không",
        ("price_promotion",),
        ("tủ lạnh", "xiaomi"),
    ),
    ScenarioCase(
        "price_07", "Đối tượng đặc biệt",
        "Macbook Air M2 bản base có áp dụng ưu đãi Học sinh sinh viên không",
        ("price_promotion",),
        ("macbook", "m2"),
    ),
    ScenarioCase(
        "price_08", "Đối tượng đặc biệt",
        "SVIP mua iPhone 17prm 256 còn bao nhiêu",
        ("price_promotion",),
        ("iphone", "17", "pro max", "256"),
        scenarios_exclude=("category_filter_browse",),
    ),
    ScenarioCase(
        "price_09", "Đối tượng đặc biệt",
        "HSSV mua iPad có ưu đãi gì không",
        ("price_promotion",),
        ("ipad",),
    ),
    # --- Kiểm tra tồn kho ---
    ScenarioCase(
        "stock_01", "Tồn cửa hàng",
        "Shop mình còn máy iPhone 16 Plus 256 màu hồng không",
        ("shop_stock",),
        ("iphone", "16", "plus", "256", "hồng"),
        scenarios_exclude=("category_filter_browse",),
    ),
    ScenarioCase(
        "stock_02", "Tồn cửa hàng",
        "Mã Sony WH-1000XM5 còn hàng trưng bày hay chỉ còn hàng nguyên seal",
        ("stock_status",),
        ("sony", "wh", "1000xm5"),
    ),
    ScenarioCase(
        "stock_03", "Tồn cửa hàng",
        "iPhone 17prm còn tồn những màu nào",
        ("shop_stock",),
        ("iphone", "17", "pro max"),
    ),
    ScenarioCase(
        "stock_04", "Tồn cửa hàng",
        "Cửa hàng có đủ tồn 3 cái camera Ezviz H3C không",
        ("shop_stock",),
        ("ezviz", "h3c"),
    ),
    ScenarioCase(
        "stock_05", "Shop lân cận",
        "Gần 288 3 tháng 3 có shop nào còn tồn iPhone 16 Pro 128 Titan sa mạc không",
        ("shop_stock",),
        ("iphone", "16", "pro", "128", "titan"),
    ),
    ScenarioCase(
        "stock_06", "Shop lân cận",
        "Tìm cửa hàng gần nhất có đủ combo sạc và cáp Baseus Dura",
        ("shop_stock", "combo"),
        ("baseus", "dura"),
    ),
    ScenarioCase(
        "stock_07", "Hàng đang về",
        "17 prm 256gb trắng khi nào hàng về tới shop",
        ("incoming_stock",),
        ("17", "pro max", "256", "trắng"),
    ),
    # --- Chương trình ưu đãi / trade-in ---
    ScenarioCase(
        "trade_01", "Trade-in",
        "Lên đời iPhone 16 Pro Max từ máy cũ được công ty trợ giá thêm bao nhiêu",
        ("trade_in", "price_promotion"),
        ("iphone", "16", "pro max"),
    ),
    ScenarioCase(
        "trade_02", "Trade-in",
        "Mã Samsung S24 series tháng này có trợ giá Trade-in không",
        ("trade_in",),
        ("samsung", "s24"),
    ),
    ScenarioCase(
        "trade_03", "Trade-in",
        "OPPO Find X9 tháng này trợ giá bao nhiêu % tối đa bao nhiêu",
        ("price_promotion",),
        ("oppo", "find", "x9"),
    ),
    ScenarioCase(
        "trade_04", "Trade-in",
        "Thu cũ S25 lên S26 có được trợ giá thêm không",
        ("trade_in",),
        ("s25", "s26"),
    ),
    ScenarioCase(
        "trade_05", "Điều kiện trade-in",
        "Máy lock, kính vỡ nhẹ có được tham gia chương trình thu cũ đổi mới của iPhone 16 không",
        ("trade_in",),
        ("iphone", "16"),
    ),
    ScenarioCase(
        "trade_06", "Điều kiện trade-in",
        "Khách muốn trade-in từ Oppo sang iPhone thì có được nhận voucher trợ giá 2 triệu không",
        ("trade_in", "price_promotion"),
        ("oppo", "iphone"),
    ),
    ScenarioCase(
        "trade_07", "Điều kiện trade-in",
        "Laptop ASUS cũ XXX có tham gia trade-in được không",
        ("trade_in",),
        ("asus",),
    ),
    # --- Trả góp ---
    ScenarioCase(
        "inst_01", "Trả góp CTTC",
        "Check gói trả góp 0% của Home Credit cho iPhone 16 128gb, trả trước thấp nhất bao nhiêu",
        ("installment", "price_promotion"),
        ("iphone", "16", "128"),
    ),
    ScenarioCase(
        "inst_02", "Trả góp CTTC",
        "Mua trả góp kỳ hạn 6 tháng mã Xiaomi 14 Ultra thì mỗi tháng đóng bao nhiêu tiền",
        ("installment", "price_promotion"),
        ("xiaomi", "14", "ultra"),
    ),
    ScenarioCase(
        "inst_03", "Trả góp CTTC",
        "Trả góp 17prm 6 tháng qua Home Credit thì chênh lệch bao nhiêu so với trả thẳng",
        ("installment", "price_promotion"),
        ("17", "pro max"),
    ),
    ScenarioCase(
        "inst_04", "Trả góp CTTC",
        "Trả góp iPhone 16 tháng có miễn phí miễn lãi không",
        ("installment",),
        ("iphone", "16"),
    ),
    ScenarioCase(
        "inst_05", "Trả góp thẻ",
        "Thẻ VIB có ưu đãi gì khi trả góp không",
        ("installment", "price_promotion"),
    ),
    ScenarioCase(
        "inst_06", "Trả góp thẻ",
        "Thẻ tín dụng Techcombank có được miễn phí chuyển đổi trả góp 12 tháng khi mua Macbook không",
        ("installment",),
        ("macbook",),
    ),
    # --- Bảo hành ---
    ScenarioCase(
        "warr_01", "BH mở rộng",
        "Gói bảo hành VIP rơi vỡ vào nước 12 tháng của iPhone 16 Pro Max giá bao nhiêu",
        ("warranty", "price_promotion"),
        ("iphone", "16", "pro max"),
    ),
    ScenarioCase(
        "warr_02", "BH mở rộng",
        "Mua kèm Apple Care+ cho Macbook Air lúc thanh toán được giảm mấy phần trăm",
        ("warranty", "price_promotion"),
        ("macbook", "air"),
    ),
    ScenarioCase(
        "warr_03", "Đổi trả",
        "Máy iPhone mua được 15 ngày bị lỗi sọc màn hình thì chính sách shop mình đổi mới hay gửi hãng",
        ("warranty", "faq_policy"),
    ),
    ScenarioCase(
        "warr_04", "Đổi trả",
        "Khách mua phụ kiện cáp sạc dùng 3 ngày không thích có được trả lại hoàn tiền không",
        ("warranty", "faq_policy"),
    ),
    ScenarioCase(
        "warr_05", "Đổi trả",
        "Sạc dự phòng mua 1 tháng bị lỗi thì có được 1 đổi 1 không",
        ("warranty", "faq_policy"),
        ("sạc dự phòng",),
    ),
    # --- Tư vấn chọn mua ---
    ScenarioCase(
        "adv_01", "So sánh phiên bản",
        "Tư vấn khách muốn đổi từ iPhone 15 Pro Max lên 16 Pro Max thì có gì khác biệt đáng tiền",
        ("compare", "advice"),
        compare_parts=("iPhone 15 Pro Max", "16 Pro Max"),
    ),
    ScenarioCase(
        "adv_02", "So sánh phiên bản",
        "So sánh S26 Ultra và S25 Ultra, nên mua con nào hơn",
        ("compare", "advice"),
        compare_parts=("S26 Ultra", "S25 Ultra"),
    ),
    ScenarioCase(
        "adv_03", "So sánh phiên bản",
        "Đang dùng iPhone 16 Pro có nên đổi qua S26 Ultra không",
        ("compare", "advice"),
        compare_parts=("iPhone 16 Pro", "S26 Ultra"),
    ),
    ScenarioCase(
        "adv_04", "Phân khúc",
        "Tầm giá 15 triệu chọn điện thoại của hãng nào, có những dòng máy nào phù hợp",
        ("advice", "budget_browse"),
        keywords_is_filter_url=True,
    ),
    ScenarioCase(
        "adv_05", "Phân khúc",
        "So sánh Redmi note 15 với Nubia Neo 3 trong tầm giá",
        ("compare",),
        compare_parts=("Redmi note 15", "Nubia Neo 3"),
    ),
    ScenarioCase(
        "adv_06", "Nhu cầu cụ thể",
        "Khách mua máy tầm 7 triệu mua tặng mẹ, ưu tiên pin trâu màn hình to",
        ("advice", "budget_browse"),
        keywords_is_filter_url=True,
    ),
    ScenarioCase(
        "adv_07", "Nhu cầu cụ thể",
        "Tư vấn laptop gaming tầm 25 triệu cho sinh viên đồ họa",
        ("advice", "budget_browse"),
        keywords_is_filter_url=True,
    ),
    # --- Thông số kỹ thuật ---
    ScenarioCase(
        "spec_01", "Thông số phần cứng",
        "Mã Asus ROG Strix màn hình bao nhiêu Hz, dùng card đồ họa gì",
        ("specs", "price_promotion"),
        ("asus", "rog"),
    ),
    ScenarioCase(
        "spec_02", "Thông số phần cứng",
        "iPhone 16 Pro Max cảm biến camera chính bao nhiêu megapixel, zoom quang mấy x",
        ("specs", "price_promotion"),
        ("iphone", "16", "pro max"),
    ),
    ScenarioCase(
        "spec_03", "Thông số phần cứng",
        "Chip Exynos trên con S24 dùng có bị nóng máy không",
        ("specs",),
        ("s24",),
    ),
    ScenarioCase(
        "spec_04", "Sạc / phụ kiện",
        "Samsung Flip 7 sạc tối đa bao nhiêu W, mua củ sạc nào thì vừa",
        ("specs", "price_promotion"),
        ("flip", "7"),
    ),
    ScenarioCase(
        "spec_05", "Sạc / phụ kiện",
        "iPad Air 6 có dùng chung được với bút Apple Pencil 2 không",
        ("specs",),
        ("ipad", "air"),
    ),
)
