from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    app_token: str = Field(min_length=24)
    onebot_access_token: str = Field(min_length=24)
    group_whitelist: str = 'demo-class'
    timezone: str = 'Asia/Shanghai'
    data_dir: Path = Path('data')
    model_base_url: str = ''
    model: str = ''
    model_api_key: str = ''
    model_daily_calls: int = Field(default=30, ge=0, le=10000)
    model_min_interval: float = Field(default=2, ge=0)
    model_timeout: float = Field(default=20, ge=1, le=120)
    model_max_tokens: int = Field(default=2200, ge=100, le=8000)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retention_days: int = Field(default=90, ge=1)
    ocr_lang: str = 'chi_sim+eng'
    tessdata_dir: str = ''
    host: str = '127.0.0.1'
    port: int = 8080
    napcat_webui_port: int | None = Field(default=None, ge=1, le=65535)
    bundled_ui: bool = False
    @field_validator('timezone')
    @classmethod
    def tz(cls, v):
        if v != 'Asia/Shanghai':
            raise ValueError('第一版只验证 Asia/Shanghai')
        return v
    @property
    def groups(self):
        return {x.strip() for x in self.group_whitelist.split(',') if x.strip()}
