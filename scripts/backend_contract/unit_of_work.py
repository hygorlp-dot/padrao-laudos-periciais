from copy import deepcopy


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
        except Exception:
            for participant, snapshot in zip(self._participants, snapshots):
                self._restore(participant, snapshot)
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
