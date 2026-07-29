@echo off
echo Starting Backend Server (FastAPI)...
start "Backend (FastAPI)" cmd /c ".\.venv\Scripts\python -m app_web.server"

echo Starting Frontend Server (React/Vite)...
start "Frontend (React)" cmd /c "cd frontend && npm run dev"

echo =======================================================
echo ✅ Aplikasi sedang dijalankan!
echo 🌐 Frontend bisa diakses di : http://localhost:5173/
echo ⚙️  Backend API berjalan di : http://127.0.0.1:8001
echo =======================================================
echo (Jendela terminal baru telah terbuka untuk masing-masing server)
