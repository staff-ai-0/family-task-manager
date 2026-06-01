"""Default budget category tree, seeded on a family's first budget visit.

Mirrors Actual Budget's "premade categories" idea: every family starts with a
sensible group → category structure so transactions always have somewhere to
land. The tree is MX-oriented (Spanish names) and intentionally broad so the
AI categorizer has clear, distinct targets (Gasolina vs Restaurantes vs
Despensa, etc.).

``seed_default_categories`` is idempotent: it no-ops when the family already
has any (non-deleted) category group, so it is safe to call lazily on every
budget page load.
"""

import logging
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.budget import BudgetCategory, BudgetCategoryGroup

logger = logging.getLogger(__name__)

# (group_name, is_income, [category names])
DEFAULT_CATEGORY_TREE: list[tuple[str, bool, list[str]]] = [
    ("Ingresos", True, ["Salario", "Ingresos Extra", "Reembolsos"]),
    ("Mandado", False, [
        "Despensa", "Fruta y Verdura", "Carne y Pescado", "Panadería y Tortillería",
    ]),
    ("Comida Fuera", False, ["Restaurantes", "Café", "Comida Rápida", "Domicilio"]),
    ("Servicios", False, [
        "Luz", "Agua", "Gas", "Internet", "Teléfono", "Streaming y Apps",
    ]),
    ("Transporte", False, [
        "Gasolina", "Uber y Taxi", "Transporte Público",
        "Casetas y Estacionamiento", "Mantenimiento Auto",
    ]),
    ("Hogar", False, [
        "Renta o Hipoteca", "Muebles y Decoración", "Limpieza", "Reparaciones",
    ]),
    ("Salud", False, ["Farmacia", "Doctor y Consultas", "Seguro Médico"]),
    ("Entretenimiento", False, ["Cine y Salidas", "Suscripciones", "Hobbies"]),
    ("Educación", False, ["Colegiaturas", "Útiles", "Cursos"]),
    ("Personal", False, ["Ropa", "Cuidado Personal", "Regalos"]),
    ("Otros Gastos", False, ["Varios", "Comisiones Bancarias", "Impuestos"]),
]


async def seed_default_categories(db: AsyncSession, family_id: UUID) -> int:
    """Create the default group/category tree for a family if it has none.

    Idempotent — returns 0 (and writes nothing) when the family already has at
    least one non-deleted category group. Returns the number of categories
    created otherwise. Commits its own transaction.
    """
    existing = await db.scalar(
        select(func.count())
        .select_from(BudgetCategoryGroup)
        .where(
            BudgetCategoryGroup.family_id == family_id,
            BudgetCategoryGroup.deleted_at.is_(None),
        )
    )
    if existing and existing > 0:
        return 0

    created = 0
    for gi, (group_name, is_income, cat_names) in enumerate(DEFAULT_CATEGORY_TREE):
        group = BudgetCategoryGroup(
            family_id=family_id,
            name=group_name,
            is_income=is_income,
            sort_order=gi,
        )
        db.add(group)
        await db.flush()
        for ci, cat_name in enumerate(cat_names):
            db.add(BudgetCategory(
                family_id=family_id,
                group_id=group.id,
                name=cat_name,
                sort_order=ci,
            ))
            created += 1

    await db.commit()
    logger.info("seeded %d default categories for family %s", created, family_id)
    return created
