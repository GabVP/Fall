"""Operações básicas de leitura e alteração limitadas a um proprietário."""

from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, Table
from sqlalchemy.engine import RowMapping

from fall.application.ownership import OwnerScope


class OwnedRepository:
    """Vincula todas as operações oferecidas ao proprietário da sessão.

    A tabela deve possuir colunas ``id`` e ``user_id``. O chamador controla a
    transação e deve converter ausência no mesmo resultado público para um ID
    inexistente ou de outro proprietário.
    """

    def __init__(self, connection: Connection, table: Table, owner: OwnerScope) -> None:
        if not isinstance(owner, OwnerScope):
            raise TypeError("É necessário um contexto de proprietário.")
        self._connection = connection
        self._table = table
        self._owner = owner

    def get(self, key: Any) -> RowMapping | None:
        statement = self._table.select().where(
            self._table.c.id == key, self._table.c.user_id == self._owner.user_id
        )
        return self._connection.execute(statement).mappings().one_or_none()

    def update(self, key: Any, values: Mapping[str, Any]) -> bool:
        if not values or {"id", "user_id"} & values.keys():
            raise ValueError("A alteração não pode modificar a identidade ou o proprietário.")
        statement = (
            self._table.update()
            .where(self._table.c.id == key, self._table.c.user_id == self._owner.user_id)
            .values(**values)
            .returning(self._table.c.id)
        )
        return self._connection.execute(statement).scalar_one_or_none() is not None
