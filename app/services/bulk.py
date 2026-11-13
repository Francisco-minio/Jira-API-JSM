"""
Servicio para operaciones masivas en Jira (Bulk Operations).
Permite filtrar tickets con JQL o filtros estructurados y ejecutar cambios masivos
(Organizaciones, Etiquetas, Asignado, Comentarios, etc.) con soporte para simulación (Dry Run).
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.services.jira import JiraClient

logger = logging.getLogger(__name__)
settings = get_settings()

ORG_FIELD = settings.jira_organization_field_id or "customfield_10002"


def get_bulk_metadata(jira: JiraClient) -> dict[str, Any]:
    """Obtiene metadatos útiles para la interfaz de filtros: proyectos, estados y organizaciones."""
    metadata: dict[str, Any] = {
        "projects": [],
        "statuses": [],
        "organizations": [],
        "org_field": ORG_FIELD,
    }

    # 1. Proyectos
    try:
        resp = jira.session.get(f"{jira.base_url}/rest/api/3/project", timeout=15)
        if resp.ok:
            metadata["projects"] = [
                {"key": p.get("key"), "name": p.get("name")}
                for p in resp.json()
            ]
    except Exception as e:
        logger.warning(f"Error al obtener proyectos de Jira: {e}")

    # 2. Estados
    try:
        resp = jira.session.get(f"{jira.base_url}/rest/api/3/status", timeout=15)
        if resp.ok:
            # Eliminar duplicados por nombre
            seen = set()
            clean_statuses = []
            for s in resp.json():
                name = s.get("name")
                if name and name not in seen:
                    seen.add(name)
                    clean_statuses.append({
                        "id": s.get("id"),
                        "name": name,
                        "category": s.get("statusCategory", {}).get("name", "Other")
                    })
            metadata["statuses"] = sorted(clean_statuses, key=lambda x: x["name"])
    except Exception as e:
        logger.warning(f"Error al obtener estados de Jira: {e}")

    # 3. Organizaciones (JSM)
    try:
        all_orgs = []
        start = 0
        limit = 50
        while True:
            org_res = jira.list_organizations(start=start, limit=limit)
            values = org_res.get("values", [])
            all_orgs.extend(values)
            if org_res.get("isLastPage", True) or len(values) < limit or start >= 500:
                break
            start += limit
        metadata["organizations"] = [
            {"id": str(o.get("id")), "name": o.get("name")}
            for o in all_orgs
        ]
    except Exception as e:
        logger.warning(f"Error al obtener organizaciones de Jira: {e}")

    return metadata


def build_jql_from_filters(
    project: str | None = None,
    status: str | None = None,
    organization: str | None = None,
    label: str | None = None,
    search_text: str | None = None,
    custom_jql: str | None = None,
) -> str:
    """Construye un JQL a partir de filtros simples o devuelve el JQL personalizado."""
    if custom_jql and custom_jql.strip():
        return custom_jql.strip()

    clauses: list[str] = []
    if project and project.strip():
        clauses.append(f'project = "{project.strip()}"')
    if status and status.strip():
        clauses.append(f'status = "{status.strip()}"')
    if organization and organization.strip():
        clauses.append(f'Organizations = "{organization.strip()}"')
    if label and label.strip():
        clauses.append(f'labels = "{label.strip()}"')
    if search_text and search_text.strip():
        clauses.append(f'text ~ "{search_text.strip()}"')

    if not clauses:
        return "ORDER BY updated DESC"
    return " AND ".join(clauses) + " ORDER BY updated DESC"


def search_issues_for_bulk(
    jira: JiraClient,
    jql: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Busca tickets en Jira según el JQL y formatea los resultados para edición masiva."""
    fields = [
        "summary",
        "status",
        "project",
        "assignee",
        "created",
        "updated",
        "labels",
        ORG_FIELD,
    ]

    all_issues: list[dict[str, Any]] = []
    next_token = None
    batch_size = min(limit, 50)

    while len(all_issues) < limit:
        res = jira.search_issues(
            jql=jql,
            max_results=batch_size,
            next_page_token=next_token,
            extra_fields=[ORG_FIELD, "labels"],
        )
        batch = res.get("issues", [])
        for iss in batch:
            f = iss.get("fields", {})
            # Extraer organizaciones
            org_objs = f.get(ORG_FIELD) or []
            org_names = []
            if isinstance(org_objs, list):
                for o in org_objs:
                    if isinstance(o, dict):
                        org_names.append(o.get("name") or str(o.get("id")))
                    else:
                        org_names.append(str(o))

            all_issues.append({
                "key": iss.get("key"),
                "summary": f.get("summary") or "Sin resumen",
                "status": f.get("status", {}).get("name") or "Desconocido",
                "project": f.get("project", {}).get("name") or f.get("project", {}).get("key") or "",
                "assignee": f.get("assignee", {}).get("displayName") if f.get("assignee") else "Sin Asignar",
                "created": f.get("created"),
                "updated": f.get("updated"),
                "labels": f.get("labels") or [],
                "organizations": org_names,
            })
            if len(all_issues) >= limit:
                break

        next_token = res.get("nextPageToken")
        if not next_token or res.get("isLast", False) or not batch:
            break

    return all_issues


def apply_bulk_operation_single(
    jira: JiraClient,
    issue_key: str,
    operation: str,
    params: dict[str, Any],
    dry_run: bool = True,
) -> dict[str, Any]:
    """
    Ejecuta o simula la modificación de un ticket específico.
    Operaciones soportadas:
    - remove_org: { "org_id": int | str, "org_name": str }
    - add_org: { "org_id": int }
    - clear_orgs: {}
    - add_label: { "label": str }
    - remove_label: { "label": str }
    - clear_labels: {}
    - set_assignee: { "account_id": str | None }
    - add_comment: { "body": str }
    """
    if dry_run:
        # En modo simulación solo validamos la operación y retornamos éxito descriptivo
        msg = f"[Simulación] Operación '{operation}' lista para aplicarse en {issue_key}"
        if operation == "remove_org":
            msg = f"[Simulación] Se removerá la organización {params.get('org_name') or params.get('org_id')} de {issue_key}"
        elif operation == "add_org":
            msg = f"[Simulación] Se agregará la organización {params.get('org_id')} a {issue_key}"
        elif operation == "clear_orgs":
            msg = f"[Simulación] Se vaciará el campo Organización de {issue_key}"
        elif operation == "add_label":
            msg = f"[Simulación] Se añadirá la etiqueta '{params.get('label')}' a {issue_key}"
        elif operation == "remove_label":
            msg = f"[Simulación] Se quitará la etiqueta '{params.get('label')}' de {issue_key}"
        elif operation == "add_comment":
            msg = f"[Simulación] Se añadirá un comentario a {issue_key}"
        return {"key": issue_key, "success": True, "message": msg, "dry_run": True}

    # EJECUCIÓN REAL
    url = f"{jira.base_url}/rest/api/3/issue/{issue_key}"
    try:
        if operation == "remove_org":
            org_id = int(params.get("org_id"))
            # PUT update remove
            payload = {
                "update": {
                    ORG_FIELD: [
                        {"remove": org_id}
                    ]
                }
            }
            resp = jira.session.put(url, json=payload, timeout=25)
            if not resp.ok:
                # Intento alternativo con fields vacío si solo tenía esa organización
                payload_alt = {"fields": {ORG_FIELD: []}}
                resp = jira.session.put(url, json=payload_alt, timeout=25)
            if resp.status_code in (200, 204):
                return {"key": issue_key, "success": True, "message": "Organización eliminada con éxito."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "add_org":
            org_id = int(params.get("org_id"))
            payload = {
                "update": {
                    ORG_FIELD: [
                        {"add": org_id}
                    ]
                }
            }
            resp = jira.session.put(url, json=payload, timeout=25)
            if resp.status_code in (200, 204):
                return {"key": issue_key, "success": True, "message": "Organización añadida con éxito."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "clear_orgs":
            payload = {"fields": {ORG_FIELD: []}}
            resp = jira.session.put(url, json=payload, timeout=25)
            if resp.status_code in (200, 204):
                return {"key": issue_key, "success": True, "message": "Campo Organización vaciado correctamente."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "add_label":
            label = str(params.get("label", "")).strip()
            if not label:
                return {"key": issue_key, "success": False, "message": "Etiqueta vacía no permitida."}
            payload = {
                "update": {
                    "labels": [
                        {"add": label}
                    ]
                }
            }
            resp = jira.session.put(url, json=payload, timeout=25)
            if resp.status_code in (200, 204):
                return {"key": issue_key, "success": True, "message": f"Etiqueta '{label}' añadida."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "remove_label":
            label = str(params.get("label", "")).strip()
            payload = {
                "update": {
                    "labels": [
                        {"remove": label}
                    ]
                }
            }
            resp = jira.session.put(url, json=payload, timeout=25)
            if resp.status_code in (200, 204):
                return {"key": issue_key, "success": True, "message": f"Etiqueta '{label}' eliminada."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "set_assignee":
            account_id = params.get("account_id")
            # account_id puede ser None para desasignar
            payload = {"fields": {"assignee": {"accountId": account_id} if account_id else None}}
            resp = jira.session.put(url, json=payload, timeout=25)
            if resp.status_code in (200, 204):
                msg = f"Asignado a {account_id}" if account_id else "Ticket desasignado"
                return {"key": issue_key, "success": True, "message": msg}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        elif operation == "add_comment":
            comment_text = str(params.get("body", "")).strip()
            if not comment_text:
                return {"key": issue_key, "success": False, "message": "Texto del comentario vacío."}
            # En Jira Cloud API v3, los comentarios pueden usar ADF o formato de texto
            comment_url = f"{jira.base_url}/rest/api/3/issue/{issue_key}/comment"
            payload = {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": comment_text}
                            ]
                        }
                    ]
                }
            }
            resp = jira.session.post(comment_url, json=payload, timeout=25)
            if resp.status_code in (200, 201):
                return {"key": issue_key, "success": True, "message": "Comentario añadido con éxito."}
            return {"key": issue_key, "success": False, "message": f"Error Jira {resp.status_code}: {resp.text}"}

        else:
            return {"key": issue_key, "success": False, "message": f"Operación no soportada: {operation}"}

    except Exception as e:
        logger.error(f"Excepción al modificar {issue_key}: {e}")
        return {"key": issue_key, "success": False, "message": f"Error de conexión o timeout: {str(e)}"}
