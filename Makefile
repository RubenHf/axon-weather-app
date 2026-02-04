.PHONY: dev dev-backend dev-frontend

dev:
	@echo "Starting backend and frontend..."
	@(cd backend && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000) & \
	 (cd frontend && bun run dev) & \
	 wait

dev-backend:
	cd backend && uv run uvicorn main:app --reload --host 127.0.0.1 --port 8000

dev-frontend:
	cd frontend && bun dev