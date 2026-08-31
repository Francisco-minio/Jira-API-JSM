# Jira Helpdesk Report

Aplicación para consolidar datos de Jira Service Management y generar reportes de:

- horas por agente
- incidencias
- clientes
- gráficos diarios y mensuales
- capacidad esperada de 40 horas semanales
- exclusión de festivos chilenos

## Stack

- FastAPI
- SQLAlchemy
- PostgreSQL
- Docker / Docker Compose
- Jira REST API
- Chart.js para el dashboard

## Variables de entorno

Copiar `.env.example` a `.env` y completar:

- `JIRA_BASE_URL`
- `JIRA_EMAIL`
- `JIRA_API_TOKEN`
- `JIRA_JQL`
- `DATABASE_URL`

## Ejecutar local

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Ejecutar con Docker

```bash
docker compose up --build
```

## Endpoints principales

- `GET /`
- `POST /api/sync`
- `GET /api/reports/overview`
- `GET /api/reports/daily`
- `GET /api/reports/monthly`
- `GET /api/reports/agents`

## Notas de sincronización

La app compara cada issue con el `updated` de Jira y solo vuelve a consultar worklogs cuando detecta cambios.
Los worklogs se guardan por `jira_worklog_id`, lo que permite sincronización incremental sin duplicados.

