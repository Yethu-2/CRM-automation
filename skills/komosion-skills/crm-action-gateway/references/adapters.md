# CRM adapters

Same gateway rules apply to every CRM. Only tool names differ; list the connected server's tools at runtime and map them to the three tiers.

**Pipedrive MCP** (tool families seen): `searchPersons`, `searchOrganization`, `searchDeals`, `getDeal`, `getAccountContext` (pipelines, stages, custom fields; call it first) are **Read**. `addNote`, `addActivity`, `updateDeal`, `updatePerson`, `addPerson`, `addDeal` are **Execute** and require approval. Deal stage changes and won/lost are always human-reviewed.

**Twenty MCP**: map organisation, person, opportunity read tools to **Read**; create/update/task tools to **Execute**. Confirm tool names from the server's listing before use.

Initial rollout scope: read, propose, execute-after-approval only. Widen only after review data shows low edit and rejection rates for a specific action type.
