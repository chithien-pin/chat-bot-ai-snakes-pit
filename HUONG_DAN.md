# Hướng dẫn sử dụng Telegram Bot tư vấn CellphoneS

Bot tự động tìm sản phẩm trên [cellphones.com.vn](https://cellphones.com.vn), lấy giá / thông số / tồn kho, rồi dùng **Google Gemini** để trả lời câu hỏi của bạn bằng tiếng Việt.

---

## Mục lục

1. [Bot làm được gì?](#1-bot-làm-được-gì)
2. [Cài đặt lần đầu](#2-cài-đặt-lần-đầu)
3. [Cấu hình (.env)](#3-cấu-hình-env)
4. [Chạy bot](#4-chạy-bot)
5. [Cách dùng trên Telegram](#5-cách-dùng-trên-telegram)
6. [Lệnh có sẵn](#6-lệnh-có-sẵn)
7. [Ví dụ câu hỏi](#7-ví-dụ-câu-hỏi)
8. [Luồng xử lý](#8-luồng-xử-lý)
9. [Xử lý sự cố](#9-xử-lý-sự-cố)
10. [Bảo mật](#10-bảo-mật)

---

## 1. Bot làm được gì?

| Tính năng | Mô tả |
|-----------|--------|
| Tìm sản phẩm | Tìm theo tên / model trên CellphoneS |
| Giá & khuyến mãi | Hiển thị giá bán, giá gốc (nếu có) |
| Thông số kỹ thuật | RAM, chip, màn hình, pin, v.v. |
| Tình trạng hàng | Còn hàng / tạm hết hàng |
| Tư vấn AI | Gemini tổng hợp câu trả lời ngắn gọn, tiếng Việt |
| Link sản phẩm | Nút **🔗 Xem trên Cellphones** dẫn thẳng trang gốc |

---

## 2. Cài đặt lần đầu

### Yêu cầu

- **Python 3.10 trở lên** (đã test trên 3.14)
- Kết nối Internet
- Token bot Telegram + API key Gemini

### Các bước

```bash
# 1. Vào thư mục dự án
cd /Users/batterypin/Desktop/ChatBotSnakePit

# 2. Tạo môi trường ảo
python3 -m venv .venv

# 3. Kích hoạt môi trường ảo
source .venv/bin/activate          # macOS / Linux
# .venv\Scripts\activate           # Windows

# 4. Cài thư viện
pip install -r requirements.txt

# 5. Tạo file cấu hình
cp .env.example .env
# Mở .env và điền token/key (xem mục 3)
```

---

## 3. Cấu hình (.env)

Mở file `.env` và điền các biến sau:

| Biến | Bắt buộc | Mô tả |
|------|----------|--------|
| `TELEGRAM_BOT_TOKEN` | Có | Token từ [@BotFather](https://t.me/BotFather) |
| `GEMINI_API_KEY` | Có | API key từ [Google AI Studio](https://aistudio.google.com/apikey) |
| `GROUP_CHAT_ID` | Không* | ID group/chat bot được phép trả lời |
| `CPS_PROVINCE_ID` | Không | Mã tỉnh CellphoneS (mặc định `30` = TP.HCM) |
| `GEMINI_MODEL` | Không | Model Gemini (mặc định `gemini-3.5-flash`) |
| `LLM_PROVIDER` | Không | `gemini` (mặc định) hoặc `deepseek` để test |
| `DEEPSEEK_API_KEY` | Khi dùng DeepSeek | API key DeepSeek |
| `DEEPSEEK_MODEL` | Không | `deepseek-chat` hoặc `deepseek-reasoner` |

\* Nếu **để trống** `GROUP_CHAT_ID`, bot sẽ trả lời **mọi** chat (tin nhắn riêng hoặc group).

### Lấy `TELEGRAM_BOT_TOKEN`

1. Mở Telegram → tìm **@BotFather**
2. Gửi `/newbot` (hoặc `/token` nếu bot đã có)
3. Copy token dạng `123456789:ABCdef...` vào `.env`

### Lấy `GEMINI_API_KEY`

1. Vào [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Tạo API key mới
3. Dán vào `.env`

### Lấy `GROUP_CHAT_ID`

Cách 1 — dùng bot [@userinfobot](https://t.me/userinfobot) hoặc [@getidsbot](https://t.me/getidsbot):

1. Thêm bot đó vào group của bạn
2. Gửi một tin nhắn trong group
3. Bot sẽ trả về **Chat ID** (số âm, ví dụ `-5013058010`)

Cách 2 — đọc log khi chạy bot (tạm bỏ `GROUP_CHAT_ID` trong `.env`, gửi tin nhắn, xem log).

### Thêm bot vào group

1. Mở group Telegram cần dùng bot
2. **Thêm thành viên** → chọn bot của bạn
3. Nếu bot **không đọc được tin nhắn** trong group:
   - Mở [@BotFather](https://t.me/BotFather)
   - `/mybots` → chọn bot → **Bot Settings** → **Group Privacy** → **Turn off**

---

## 4. Chạy bot

```bash
cd /Users/batterypin/Desktop/ChatBotSnakePit
source .venv/bin/activate
python bot.py
```

Khi thấy log tương tự:

```text
INFO | Khởi động bot... (Python 3.14.x)
INFO | Chỉ phản hồi group/chat ID: -5013058010
INFO | Bot đang chạy — nhấn Ctrl+C để dừng.
```

→ Bot đã sẵn sàng nhận tin nhắn.

**Dừng bot:** nhấn `Ctrl + C` trong terminal.

### Chạy nền (tùy chọn)

```bash
nohup python bot.py > bot.log 2>&1 &
```

Xem log: `tail -f bot.log`

### Test scraper (không cần Telegram)

```bash
python scraper.py "iphone 15 pro max"
```

---

## 5. Cách dùng trên Telegram

1. Mở **group** (hoặc chat riêng) đã cấu hình
2. Gửi câu hỏi bằng **tiếng Việt**, ví dụ: `iPhone 15 Pro Max giá bao nhiêu?`
3. Bot phản hồi theo các bước:
   - `🔍 Đang tìm kiếm thông tin...`
   - `📦 Đang lấy thông số chi tiết...`
   - `🤖 Đang phân tích với Gemini AI...`
4. Nhận câu trả lời + nút **🔗 Xem trên Cellphones**

**Lưu ý:**

- Chỉ cần gửi **tin nhắn thường**, không bắt buộc dùng lệnh `/`
- Câu hỏi càng **cụ thể** (tên sản phẩm, dung lượng) thì kết quả càng chính xác
- Giá và tồn kho lấy từ website tại thời điểm bot chạy — có thể thay đổi sau đó

---

## 6. Lệnh có sẵn

| Lệnh | Chức năng |
|------|-----------|
| `/start` | Lời chào và ví dụ câu hỏi |
| `/help` | Hướng dẫn ngắn trong Telegram |

Mọi tin nhắn **không phải lệnh** đều được coi là câu hỏi tư vấn sản phẩm.

---

## 7. Ví dụ câu hỏi

```
iPhone 15 Pro Max giá bao nhiêu?
Samsung Galaxy S25 Ultra còn hàng không?
Laptop gaming dưới 20 triệu
MacBook Air M3 thông số như thế nào?
Tai nghe Sony WH-1000XM5 giá CellphoneS
```

Bot sẽ:

- Tìm sản phẩm liên quan nhất trên CellphoneS
- Lấy chi tiết sản phẩm **đầu tiên** trong kết quả
- Gemini trả lời dựa trên dữ liệu đó

---

## 8. Luồng xử lý

```text
Bạn gửi câu hỏi
       ↓
Tìm kiếm trên CellphoneS (API)
       ↓
Vào trang chi tiết sản phẩm đầu tiên (HTML)
       ↓
Gửi dữ liệu + câu hỏi → Gemini AI
       ↓
Trả lời Telegram (Markdown + nút link)
```

**Giới hạn:** Mỗi tin nhắn tối đa **4096 ký tự** (Telegram); nội dung dài sẽ được rút gọn.

---

## 9. Xử lý sự cố

### Bot không phản hồi trong group

| Kiểm tra | Cách xử lý |
|----------|------------|
| Bot có đang chạy? | Xem terminal / `bot.log` |
| `GROUP_CHAT_ID` đúng? | So sánh ID group với `.env` |
| Bot đã vào group? | Thêm lại bot vào group |
| Privacy Mode | Tắt qua BotFather (mục 3) |
| Bot chỉ trả lời 1 group | Đúng thiết kế nếu đã set `GROUP_CHAT_ID` |

### `RuntimeError: There is no current event loop`

- Dùng bản `bot.py` mới nhất (đã có `_ensure_event_loop()`)
- Hoặc chạy: `python bot.py` (không gọi module lạ)

### Lỗi Gemini (404 model / quota)

- Đổi `GEMINI_MODEL` trong `.env`, ví dụ: `gemini-3.5-flash` (mới nhất) hoặc `gemini-3.1-flash-lite` (rẻ hơn)
- Bot tự thử nhiều model dự phòng
- Nếu báo **quota exceeded**: đợi vài phút hoặc kiểm tra hạn mức API key

### Không tìm thấy sản phẩm

- Viết lại tên sản phẩm rõ hơn (ví dụ: `iPhone 15 Pro Max 256GB` thay vì `iphone mới`)
- Kiểm tra sản phẩm có trên cellphones.com.vn không

### Tin nhắn lỗi định dạng Markdown

- Bot tự gửi lại dạng plain text nếu Markdown lỗi
- Thường không ảnh hưởng nội dung chính

---

## 10. Bảo mật

- **Không** chia sẻ file `.env` hoặc commit lên GitHub
- **Không** gửi token/key trong group chat công khai
- Nếu lộ token: tạo lại qua BotFather / Google AI Studio
- File `.env` đã được liệt kê trong `.gitignore`

---

## Cấu trúc mã nguồn (tham khảo)

| File | Vai trò |
|------|---------|
| `bot.py` | Chạy bot, xử lý Telegram |
| `scraper.py` | Tìm & scrape CellphoneS |
| `gemini_client.py` | Gọi Gemini phân tích |
| `config.py` | Đọc biến môi trường |
| `.env` | Token và cấu hình riêng (không commit) |

---

## Hỗ trợ nhanh

| Việc cần làm | Lệnh |
|--------------|------|
| Cài lại thư viện | `pip install -r requirements.txt` |
| Chạy bot | `python bot.py` |
| Test tìm kiếm | `python scraper.py "tên sản phẩm"` |

Nếu gặp lỗi, copy **toàn bộ log** trong terminal (từ dòng `ERROR` / `Traceback`) để debug.
