import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from job_store import JobStore
from service_config import ServiceSettings
raise SystemExit(0 if JobStore(ServiceSettings.from_env().db_path).health()['active_workers'] else 1)
