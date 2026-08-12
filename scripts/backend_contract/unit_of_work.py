from copy import deepcopy


class RollbackError(RuntimeError):
    def __init__(self, original_error, restore_errors):
        super().__init__("Falha ao restaurar integralmente a UnitOfWork")
        self.original_error = original_error
        self.restore_errors = tuple(restore_errors)


class UnitOfWork:
    def __init__(self, *participants):
        self._participants = participants

    @staticmethod
    def _snapshot(participant):
        return participant.snapshot() if hasattr(participant, "snapshot") else deepcopy(participant)

    @staticmethod
    def _restore(participant, snapshot):
        if hasattr(participant, "restore"):
            participant.restore(snapshot)
        elif isinstance(participant, list):
            participant[:] = snapshot
        elif isinstance(participant, dict):
            participant.clear()
            participant.update(snapshot)

    def execute(self, operation):
        snapshots = [self._snapshot(item) for item in self._participants]
        try:
            return operation()
        except Exception as original_error:
            restore_errors = []
            for participant, snapshot in reversed(tuple(zip(self._participants, snapshots))):
                try:
                    self._restore(participant, snapshot)
                except Exception as restore_error:
                    restore_errors.append(restore_error)
            if restore_errors:
                raise RollbackError(original_error, restore_errors) from original_error
            raise

    def execute_material_change(self, update, graph, upstream_id, audit_log, audit_event):
        """Executa update, invalidação transitiva e auditoria no mesmo rollback."""
        if graph not in self._participants or audit_log not in self._participants:
            raise ValueError("Grafo e audit log devem participar da UnitOfWork")

        def operation():
            result = update()
            invalidated = graph.invalidate_dependents(upstream_id)
            audit_log.append(audit_event)
            return result, invalidated

        return self.execute(operation)
