import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    openai_api_key: str
    twilio_account_sid: str
    twilio_auth_token: str
    twilio_phone_number: str
    public_base_url: str
    business_name: str
    realtime_model: str
    realtime_voice: str

    @classmethod
    def load(cls) -> "Settings":
        return cls(
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
            twilio_account_sid=os.getenv("TWILIO_ACCOUNT_SID", ""),
            twilio_auth_token=os.getenv("TWILIO_AUTH_TOKEN", ""),
            twilio_phone_number=os.getenv("TWILIO_PHONE_NUMBER", ""),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/"),
            business_name=os.getenv("BUSINESS_NAME", "Sunrise Dental Clinic"),
            realtime_model=os.getenv("REALTIME_MODEL", "gpt-4o-realtime-preview"),
            realtime_voice=os.getenv("REALTIME_VOICE", "shimmer"),
        )

    @property
    def twilio_configured(self) -> bool:
        return bool(
            self.twilio_account_sid
            and self.twilio_auth_token
            and self.twilio_phone_number
        )


settings = Settings.load()
