# CPS Bot Dashboard (Next.js)

Analytics dashboard + **AI Chat** standalone tại `/chat`.

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

- Dashboard analytics: http://localhost:3000 (cần `DASHBOARD_PASSWORD` nếu đã cấu hình)
- **AI Chat**: http://localhost:3000/chat — **chỉ nhập tên**, không cần mật khẩu dashboard

**Docker:**

```bash
docker compose --profile ui up -d --build
```

## Ngrok (chia sẻ chat nội bộ)

```bash
./scripts/tunnel_dashboard.sh
```

Gửi link: `https://xxxx.ngrok-free.app/chat` — người dùng nhập tên rồi chat (không cần pass dashboard).

## Trang

| Route | Mô tả |
|-------|--------|
| `/login` | Đăng nhập dashboard (mật khẩu) |
| `/` | Overview KPI + charts |
| `/chat` | AI Chat — nhập tên trước, full-screen, không sidebar |
| `/pipeline` | Pipeline trace |
| `/messages` | Bảng tin nhắn |
| `/sessions` | sessions.db |
| `/feedback` | Feedback training |
| `/data` | Sync health |
