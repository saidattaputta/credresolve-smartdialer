from dotenv import load_dotenv
import os

load_dotenv()

APP_NAME = os.getenv("APP_NAME", "CredResolve SmartDialer")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./smartdialer.db")
