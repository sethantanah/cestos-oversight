import asyncio, json
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.core.config import get_settings
async def main():
 s=get_settings()
 print(json.dumps({'scheduler_enabled':s.scheduler_enabled,'interval':s.scheduler_interval_seconds,'environment':s.app_env,'smtp_host_configured':bool(s.smtp_host),'smtp_sender_configured':bool(s.smtp_from)}))
 e=create_async_engine(s.database_url,connect_args={'timeout':10})
 try:
  async with e.connect() as c:
   await c.execute(text('SET TRANSACTION READ ONLY'))
   queries={
    'matching_documents': "SELECT d.title,d.document_type,d.expiry_date,d.verification_status,d.is_active FROM employee_documents d JOIN employees e ON e.id=d.employee_id WHERE e.employee_number='EMP-000012' AND lower(e.last_name)='flomo'",
    'schedules': "SELECT id,title,domain,rule_type,lead_time_days,frequency,delivery_method,is_active,last_run_at,next_run_at,jsonb_array_length(recipient_user_ids) AS explicit_recipients,recipient_roles FROM notification_schedules",
    'email_queue': "SELECT status,kind,count(*),max(last_error) AS last_error FROM email_deliveries GROUP BY status,kind",
    'schedule_notifications': "SELECT schedule_id,count(*) FROM notifications WHERE schedule_id IS NOT NULL GROUP BY schedule_id"}
   for label,query in queries.items():
    rows=(await c.execute(text(query))).mappings().all(); print(label,json.dumps([dict(r) for r in rows],default=str))
 except Exception as exc: print('Diagnostic failed:',type(exc).__name__)
 finally: await e.dispose()
asyncio.run(main())
