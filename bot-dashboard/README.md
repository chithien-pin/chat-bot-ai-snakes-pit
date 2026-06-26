# CPS Bot Dashboard (Next.js)

Analytics dashboard — UI theo phong cách [Analytics Dashboard (Figma Community)](https://www.figma.com/design/DB2Dk2ygyP3YXoC4QPJlW9/Analytics-Dashboard--Community-).

## Chạy

**Terminal 1 — API backend:**

```bash
cd ..
.venv/bin/python dashboard_api.py
```

**Terminal 2 — Next.js:**

```bash
cp .env.local.example .env.local
npm install
npm run dev
```

Mở http://localhost:3000 — nếu đã đặt `DASHBOARD_PASSWORD` sẽ chuyển tới `/login`.

## Bảo mật (truy cập qua internet)

1. Đặt **cùng một mật khẩu** ở cả hai file:
   - `.env` gốc: `DASHBOARD_PASSWORD=...`
   - `bot-dashboard/.env.local`: `DASHBOARD_PASSWORD=...`
2. Khởi động lại `dashboard_api.py` và `npm run dev`.
3. Cài ngrok (1 lần) và đăng ký authtoken: https://dashboard.ngrok.com/get-started/your-authtoken

```bash
ngrok config add-authtoken <token-cua-ban>
```

4. Mở tunnel (link ngẫu nhiên, không cần domain):

```bash
chmod +x scripts/tunnel_dashboard.sh
./scripts/tunnel_dashboard.sh
```

Ngrok in ra URL dạng `https://xxxx.ngrok-free.app` — gửi link này cho người cần xem; họ phải nhập mật khẩu tại `/login`.

Để tắt auth (chỉ dev local): để trống `DASHBOARD_PASSWORD` ở cả hai file.

## Trang

| Route | Mô tả |
|-------|--------|
| `/login` | Đăng nhập bằng mật khẩu |
| `/` | Overview KPI + charts |
| `/pipeline` | Pipeline trace từng tin nhắn |
| `/messages` | Bảng tin nhắn |
| `/sessions` | sessions.db |
| `/data` | Sync health |
