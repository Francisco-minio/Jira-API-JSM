from __future__ import annotations

import logging
from datetime import date, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from app.db import SessionLocal

logger = logging.getLogger("uvicorn.error")
scheduler = BackgroundScheduler()


def run_scheduled_sync():
    logger.info("Iniciando sincronización automática programada de Jira...")
    db = SessionLocal()
    result = None
    error = None
    try:
        from app.services.sync import sync_from_jira
        to_date = date.today()
        # Sincronizamos las últimas 2 semanas
        from_date = to_date - timedelta(days=14)
        result = sync_from_jira(db, from_date=from_date, to_date=to_date)
        logger.info(f"Sincronización periódica de Jira completada: {result}")
    except Exception as e:
        error = e
        logger.exception(f"Error durante la sincronización periódica de Jira: {e}")
    finally:
        db.close()
        try:
            from app.services.notifications import notify_sync_result
            notify_sync_result(result, error)
        except Exception as ne:
            logger.error(f"Error al enviar notificaciones de sincronización: {ne}")


def start_scheduler(sync_interval_hours: int):
    try:
        # Programar la sincronización periódica (intervalo configurable)
        scheduler.add_job(
            run_scheduled_sync,
            "interval",
            hours=sync_interval_hours,
            id="jira_sync_job",
            replace_existing=True
        )
        scheduler.start()
        logger.info(f"Programador de tareas iniciado (sincronización cada {sync_interval_hours} horas)")
        
        # Programamos una sincronización inmediata en segundo plano para validar funcionamiento al arrancar
        scheduler.add_job(run_scheduled_sync, "date", id="initial_jira_sync")
    except Exception as e:
        logger.error(f"No se pudo iniciar el programador de tareas: {e}")


def shutdown_scheduler():
    logger.info("Apagando programador de tareas...")
    try:
        scheduler.shutdown()
        logger.info("Programador de tareas apagado con éxito.")
    except Exception as e:
        logger.error(f"Error al apagar el programador: {e}")
