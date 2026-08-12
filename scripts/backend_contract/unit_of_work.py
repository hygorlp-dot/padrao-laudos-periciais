from copy import deepcopy


class RollbackError(RuntimeError):
    def __init__(self, original_error, restore_errors):
        super().__init__("Falha ao restaurar integralmente a UnitOfWork")
        self.original_error = original_error
        self.restore_errors = tuple(restore_errors)


class UnitOfWork:
    def __init__(self, *participants):
        strategies = []
        for participant in participants:
            snapshot = getattr(participant, "snapshot", None)
            restore = getattr(participant, "restore", None)
            protocol_pair = callable(snapshot) and callable(restore)
            if protocol_pair:
                strategies.append("protocol")
            elif isinstance(participant, list):
                strategies.append("list")
            elif isinstance(participant, dict):
                strategies.append("dict")
            else:
                raise TypeError("UnitOfWork exige participante reversível")
        self._participants = participants
        self._strategies = tuple(strategies)

    @staticmethod
    def _snapshot(participant, strategy):
        return participant.snapshot() if strategy == "protocol" else deepcopy(participant)

    @staticmethod
    def _restore(participant, snapshot, strategy):
        if strategy == "protocol":
            participant.restore(snapshot)
        elif strategy == "list":
            participant[:] = snapshot
        elif strategy == "dict":
            participant.clear()
            participant.update(snapshot)
        else:
            raise TypeError("UnitOfWork exige participante reversível")

    def execute(self, operation):
        snapshots = [
            self._snapshot(item, strategy)
            for item, strategy in zip(self._participants, self._strategies)
        ]
        try:
            return operation()
        except BaseException as original_error:
            restore_errors = []
            restoration = tuple(zip(self._participants, snapshots, self._strategies))
            for participant, snapshot, strategy in reversed(restoration):
                try:
                    self._restore(participant, snapshot, strategy)
                except BaseException as restore_error:
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
