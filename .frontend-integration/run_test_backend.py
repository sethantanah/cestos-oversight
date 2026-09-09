import os
from sqlalchemy.engine import make_url
from app.core.config import get_settings
settings=get_settings()
os.environ['DATABASE_URL']=make_url(settings.database_url).set(database='cestos_inventory_migration_test').render_as_string(hide_password=False)
os.environ['APP_ENV']='test'
os.environ['STORAGE_PROVIDER']='local'
os.environ['SUPABASE_AUTH_ENABLED']='false'
os.environ['SCHEDULER_ENABLED']='false'
get_settings.cache_clear()
import uvicorn
uvicorn.run('app.main:create_app',factory=True,host='127.0.0.1',port=8002,loop='app.core.event_loop:loop_factory',access_log=False)
