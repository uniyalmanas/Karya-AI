# Karya AI Local Startup

## 1. Start the FastAPI bridge
In `packages/agent-brain`:

```powershell
.\venv311\Scripts\python.exe -m uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

## 2. Start the Express backend
In `apps/server`:

```powershell
npm run dev
```

You should see it start on port 5001.

## 3. Start the React frontend
In `apps/web`:

```powershell
npm run dev
```

Then open the Vite URL, usually:

```text
http://localhost:5173
```

You can also start all three services from the repo root:

```powershell
npm run dev
```

## 4. Verify it
If the UI loads, the frontend is connected. Then launch a mission from the app, or test the backend:

```powershell
curl http://localhost:5001/api/agent/history
```
# Karya-AI
