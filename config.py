"""Single place where environment config is loaded and read."""
import os

from dotenv import load_dotenv

# --- session setup -----------------------------------------------------
# Local dev:  DATABASE_URL=sqlite:///data/finassist.db
# Azure:      DATABASE_URL=mssql+pyodbc://<user>:<pass>@<server>.database.windows.net/finassist?driver=ODBC+Driver+18+for+SQL+Server

load_dotenv()  # no-op for variables already set (e.g. on Azure)

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///data/finassist.db")
FINASSIST_API_URL = os.environ.get("FINASSIST_API_URL", "http://localhost:8000")
CHECKPOINT_DATABASE_PATH = os.environ.get(
    "CHECKPOINT_DATABASE_PATH", "data/finassist_checkpoints.sqlite"
)