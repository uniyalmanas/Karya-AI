import json
import os
import subprocess
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import BackgroundTasks, FastAPI
from pydantic import BaseModel

app = FastAPI(title="Karya AI Brain Execution Bridge", version="1.0.0")

BACKEND_TELEMETRY_URL = os.getenv(
    "BACKEND_TELEMETRY_URL",
    "http://127.0.0.1:5001/api/agent/telemetry-stream",
)


class MissionRequest(BaseModel):
    goal: str
    mission_id: str


def send_telemetry_payload(payload: dict):
    telemetry_payload = json.dumps(payload).encode("utf-8")
    request = Request(
        BACKEND_TELEMETRY_URL,
        data=telemetry_payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=5) as response:
            response.read()
    except (HTTPError, URLError) as exc:
        print(f"[Telemetry] Failed to send payload: {exc}")


def ship_telemetry_line(mission_id: str, line: str):
    send_telemetry_payload({
        "mission_id": mission_id,
        "log_line": line,
    })


def sanitize_log_line(line: str) -> str:
    ascii_line = line.encode("ascii", errors="ignore").decode("ascii")
    return " ".join(ascii_line.split())


def ship_mission_status(
    mission_id: str,
    status: str,
    data: dict | None = None,
    error: str | None = None,
):
    payload: dict[str, object] = {
        "mission_id": mission_id,
        "status": status,
    }
    if data is not None:
        payload["data"] = data
    if error is not None:
        payload["error"] = error

    send_telemetry_payload(payload)


def execute_agent_via_bridge(goal: str, mission_id: str):
    print("[Bridge] Launching isolated agent process.")

    current_dir = os.path.dirname(os.path.abspath(__file__))
    script_path = os.path.join(current_dir, "agent.py")
    custom_env = os.environ.copy()
    custom_env["PYTHONIOENCODING"] = "utf-8"

    try:
        process = subprocess.Popen(
            [sys.executable, script_path, goal, mission_id],
            env=custom_env,
            cwd=os.path.dirname(script_path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

        if process.stdout is not None:
            for line in process.stdout:
                clean_line = sanitize_log_line(line)
                if clean_line:
                    print(f"[Agent] {clean_line}")
                    ship_telemetry_line(mission_id, clean_line)
        else:
            print("[Bridge] stdout stream was unavailable for the agent process.")

        process.wait()

        if process.returncode == 0:
            print(f"[Bridge] Mission {mission_id} finalized cleanly.")
            result_path = os.path.join(current_dir, f"mission_{mission_id}.json")
            mission_data = None

            if os.path.exists(result_path):
                try:
                    with open(result_path, "r", encoding="utf-8") as result_file:
                        mission_data = json.load(result_file)
                except Exception as data_err:
                    print(f"[Bridge] Failed to read mission result data: {data_err}")

            if mission_data is None:
                mission_data = {"message": "Agent finished successfully."}

            ship_mission_status(mission_id, "completed", data=mission_data)
        else:
            error_text = f"Agent exited with code {process.returncode}."
            print(f"[Bridge] {error_text}")
            ship_mission_status(mission_id, "failed", error=error_text)

    except Exception as exc:
        error_text = str(exc)
        print(f"[Bridge] Critical error: {error_text}")
        ship_mission_status(mission_id, "failed", error=error_text)


@app.get("/health")
async def health():
    return {"success": True, "service": "karya-agent-brain"}


@app.post("/v1/execute-mission")
async def execute_mission(payload: MissionRequest, background_tasks: BackgroundTasks):
    print(f"[FastAPI] Received mission request: {payload.mission_id}")
    background_tasks.add_task(execute_agent_via_bridge, payload.goal, payload.mission_id)
    return {"success": True, "status": "processing", "mission_id": payload.mission_id}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
