---
name: auditoria-pericial-integrada
description: Orquestrar detector rápido, auditoria claim-evidência, proposition audit quando licenciado e pertinente, deep forensic audit, trilha e gate. Usar antes de liberar redação ou após alteração material em artefatos periciais.
---

# Auditoria pericial integrada

Executar nesta ordem:

1. Detector determinístico rápido.
2. Extração e classificação de claims.
3. Grounding pericial de todas as claims `LOAD_BEARING`.
4. Proposition Audit operacional para claims normativas, regulatórias, de vigência
   e citação, registrando resultado estruturado. Resultado material não verificável
   bloqueia o gate; nunca permanecer `PENDENTE_SKILL` em estado apto.
5. Deep forensic audit.
6. Registro da trilha profissional.
7. Gate:
   - `APTO_PARA_REDACAO` somente com claims materiais `GROUNDED`;
   - `APTO_PARA_REDACAO_COM_RESSALVAS` para `WEAKLY_GROUNDED` adequadamente ressalvada ou limitação não contraditória;
   - `BLOQUEADO_PARA_REDACAO` para claim material interpolada, não sustentada ou contradita até sua correção.

Não enviar dados privados a serviços externos e não executar automaticamente Skills catalogadas como `REFERENCE_ONLY`.
